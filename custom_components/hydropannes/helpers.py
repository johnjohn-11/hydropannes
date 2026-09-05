"""Shared helper mixin for Hydro-Pannes sensors and binary sensors.

All business logic for interpreting the Hydro-Québec API response lives here.
Both HydroPannesSensorBase (sensor.py) and HydroPannesBinarySensorBase
(binary_sensor.py) inherit from HydroPannesHelperMixin, providing a single
source of truth for outage detection, date parsing, and priority selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import AIP_REPORT_CODES

if TYPE_CHECKING:
    from datetime import datetime

    from .coordinator import HydroPannesDataUpdateCoordinator


class HydroPannesHelperMixin:
    """Mixin providing shared helper methods for Hydro-Pannes entities.

    Requires that the subclass exposes a `coordinator` attribute of type
    HydroPannesDataUpdateCoordinator (provided by CoordinatorEntity).
    """

    coordinator: HydroPannesDataUpdateCoordinator

    # ==========================================================================
    # Date parsing
    # ==========================================================================

    def _parse_dt(self, value: str | None) -> datetime | None:
        """Parse an ISO datetime string to a localized datetime, or return None."""
        if not value:
            return None
        try:
            dt = dt_util.parse_datetime(value)
            if not dt:
                return None
            return dt_util.as_local(dt)
        except (ValueError, TypeError):
            return None

    def _is_date_in_past(self, date_value: datetime | None) -> bool:
        """Return True if the given datetime is in the past."""
        if not date_value:
            return False
        return date_value <= dt_util.now()

    def _is_date_in_future(self, date_value: datetime | None) -> bool:
        """Return True if the given datetime is in the future."""
        if not date_value:
            return False
        return date_value > dt_util.now()

    # ==========================================================================
    # API data accessors
    # ==========================================================================

    def _get_main_etat(self) -> str | None:
        """Return the top-level 'etat' field from the API response."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("etat")

    def _get_interruptions(self) -> list[dict[str, Any]]:
        """Return the list of interruptions from the API response."""
        if not self.coordinator.data:
            return []
        result: list[dict[str, Any]] = self.coordinator.data.get("interruptions", [])
        return result

    # ==========================================================================
    # Interruption state checks
    # ==========================================================================

    def _is_outage_active(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption represents an active outage.

        An outage is active when:
        - The top-level etat is "N" (power out), AND
        - dateFin is absent or in the future.

        The interruption's own 'etat' field is intentionally ignored here,
        as it does not reliably indicate whether power is currently restored.
        """
        main_etat = self._get_main_etat()
        if main_etat != "N":
            return False

        date_fin = self._parse_dt(intr.get("dateFin"))
        return not date_fin or self._is_date_in_future(date_fin)

    def _is_outage_terminated(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption is terminated (power restored).

        An outage is terminated when dateFin is in the past, unless:
        - etat is "R" (postponed): the original dateFin is past but the intervention
          is rescheduled, not completed.
        - codeRemarque is an AIP_REPORT_CODE (rescheduled AIP): the original
          dateFin is the cancelled slot; termination is determined by dateFinReport.
        """
        etat = intr.get("etat")
        code_remarque = str(intr.get("codeRemarque", ""))
        if etat == "R":
            return False
        if etat == "A" and code_remarque in AIP_REPORT_CODES:
            date_fin_report = self._parse_dt(intr.get("dateFinReport"))
            if date_fin_report:
                return self._is_date_in_past(date_fin_report)
            return False
        date_fin = self._parse_dt(intr.get("dateFin"))
        return self._is_date_in_past(date_fin)

    def _is_reprise_graduelle(self, intr: dict[str, Any] | None = None) -> bool:
        """Return True when Hydro-Québec signals a gradual service restoration.

        ``repriseGraduellePossible`` is consumed from the payload root, but it
        is also listed among the interruption-level fields the integration
        knows about. Both locations are honoured so the flag is not missed if
        Hydro-Québec reports it per interruption rather than at the root.
        """
        if intr is not None and intr.get("repriseGraduellePossible"):
            return True
        data = self.coordinator.data
        return bool(data and data.get("repriseGraduellePossible"))

    def _is_planned_intervention(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption is a planned intervention (AIP)."""
        result: bool = intr.get("interruptionPlanifiee", False)
        return result

    def _is_aip_reportee(self, intr: dict[str, Any]) -> bool:
        """Return True if the planned intervention was cancelled but rescheduled.

        Detected via codeRemarque in AIP_REPORT_CODES ("91" confirmed in production,
        "93" kept as fallback). HydroQuébec sets this code when the original slot is
        cancelled and a new date is assigned via dateDebutReport/dateFinReport.
        """
        return str(intr.get("codeRemarque", "")) in AIP_REPORT_CODES

    def _is_aip_annulee(self, intr: dict[str, Any]) -> bool:
        """Return True if the planned intervention has been cancelled.

        Cancellation is detected via:
        - etat = "A" (annulée), or
        - codeRemarque = "92" (AIP cancellation code, observed empirically).

        AIP_REPORT_CODES (e.g. "91") means rescheduled, not cancelled —
        even when etat is also "A", the presence of report dates makes the AIP
        still upcoming and must not be treated as a plain cancellation.
        """
        etat = intr.get("etat")
        code_remarque = str(intr.get("codeRemarque", ""))
        if code_remarque in AIP_REPORT_CODES:
            return False
        return etat == "A" or code_remarque == "92"

    # ==========================================================================
    # Date helpers for planned interventions
    # ==========================================================================

    def _get_effective_dates(self, intr: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
        """Return the effective start and end dates for an interruption.

        For postponed (etat = "R") or rescheduled (etat = "A", AIP_REPORT_CODES) AIPs,
        uses dateDebutReport/dateFinReport when present — the API keeps the original
        dateDebut as the cancelled slot while the report fields carry the new window.
        Falls back to dateDebut/dateFin otherwise.

        Returns: (effective_debut, effective_fin)
        """
        etat = intr.get("etat")
        code_remarque = str(intr.get("codeRemarque", ""))
        if etat == "R" or (etat == "A" and code_remarque in AIP_REPORT_CODES):
            debut = self._parse_dt(intr.get("dateDebutReport"))
            fin = self._parse_dt(intr.get("dateFinReport"))
            if debut:
                return debut, fin
        return (
            self._parse_dt(intr.get("dateDebut")),
            self._parse_dt(intr.get("dateFin")),
        )

    def _is_future_planned(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption is a planned intervention with a future start."""
        if not self._is_planned_intervention(intr):
            return False

        effective_debut, _ = self._get_effective_dates(intr)
        return self._is_date_in_future(effective_debut)

    # ==========================================================================
    # Attribute building
    # ==========================================================================

    def _interruption_attributes(
        self, intr: dict[str, Any], keys: tuple[str, ...]
    ) -> dict[str, Any]:
        """Build an extra-state-attributes dict for the given interruption keys.

        Date fields (keys starting with ``date``) are parsed to a localized
        ISO string so every entity exposes timestamps in the same format;
        values that cannot be parsed fall back to the raw string. Keys whose
        value is None are omitted. Centralizing this keeps date formatting
        consistent across the info-pannes and binary sensors.
        """
        attrs: dict[str, Any] = {}
        for key in keys:
            val = intr.get(key)
            if val is None:
                continue
            if key.startswith("date") and val:
                parsed = self._parse_dt(val)
                attrs[key] = parsed.isoformat() if parsed else val
            else:
                attrs[key] = val
        return attrs

    # ==========================================================================
    # Interruption selection (priority logic)
    # ==========================================================================

    def _get_active_outage(self) -> dict[str, Any] | None:
        """Return the first active non-planned outage, or None.

        An active outage is unplanned, has main etat = "N",
        and has no dateFin or a dateFin in the future.
        """
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr):
                continue
            if self._is_outage_active(intr):
                return intr
        return None

    def _get_terminated_outage(self) -> dict[str, Any] | None:
        """Return the most recently terminated non-planned outage, or None.

        When HQ splits a single panne into multiple sections, there may be
        several terminated interruptions. Returns the one with the latest dateFin.
        """
        candidates = [
            intr
            for intr in self._get_interruptions()
            if not self._is_planned_intervention(intr) and self._is_outage_terminated(intr)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda i: self._parse_dt(i.get("dateFin")) or dt_util.utc_from_timestamp(0),
        )

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """Return the most relevant planned intervention (AIP), or None.

        Selection priority:
        1. Active planned intervention (main etat = "N", dateFin absent or future).
        2. Future non-cancelled planned intervention (effective dateDebut in future).
        3. Any future planned intervention (including rescheduled ones).
        4. Any planned intervention, including terminated (fallback).
        """
        interruptions = self._get_interruptions()
        planned = [i for i in interruptions if self._is_planned_intervention(i)]
        if not planned:
            return None

        for p in planned:
            if self._is_outage_active(p):
                return p

        for p in planned:
            if self._is_future_planned(p) and not self._is_aip_annulee(p):
                return p

        for p in planned:
            if self._is_future_planned(p):
                return p

        return planned[0]

    def _planned_supersedes_terminated(self, planned: dict[str, Any] | None) -> bool:
        """Return True when a planned intervention outranks a past outage.

        A still-relevant AIP (present, not cancelled, not terminated) should
        be displayed in place of an already-terminated unplanned outage. This
        rule is shared by _get_current_interruption and the info-pannes sensor
        so the two never drift apart.
        """
        return (
            planned is not None
            and not self._is_aip_annulee(planned)
            and not self._is_outage_terminated(planned)
        )

    def _get_current_interruption(self) -> dict[str, Any] | None:
        """Return the most relevant interruption for sensor display.

        Selection priority:
        1. Active non-planned outage (power is currently out).
        2. Terminated non-planned outage ("Service rétabli"), unless a
           non-cancelled, non-terminated AIP also exists — in that case
           the AIP takes precedence.
        3. Planned intervention (active, future, or terminated).
        4. First interruption in list (fallback).
        """
        interruption = self._get_active_outage()
        if interruption:
            return interruption

        # Yield to an active or future AIP when one coexists with a past outage.
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            planned_check = self._get_planned_intervention()
            if not self._planned_supersedes_terminated(planned_check):
                return terminated_outage
            # Fall through — AIP state supersedes the past outage.

        interruption = self._get_planned_intervention()
        if interruption:
            return interruption

        interruptions = self._get_interruptions()
        if interruptions:
            return interruptions[0]

        return None
