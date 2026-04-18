"""Shared helper mixin for Hydro-Pannes sensors and binary sensors.

All business logic for interpreting the Hydro-Québec API response lives here.
Both HydroPannesSensorBase (sensor.py) and HydroPannesBinarySensorBase
(binary_sensor.py) inherit from HydroPannesHelperMixin, providing a single
source of truth for outage detection, date parsing, and priority selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

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

        An outage is terminated when dateFin is in the past, unless etat is "R"
        (postponed): a postponed interruption has a past dateFin but is rescheduled,
        not completed.
        """
        if intr.get("etat") == "R":
            return False
        date_fin = self._parse_dt(intr.get("dateFin"))
        return self._is_date_in_past(date_fin)

    def _is_planned_intervention(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption is a planned intervention (AIP)."""
        result: bool = intr.get("interruptionPlanifiee", False)
        return result

    def _is_aip_annulee(self, intr: dict[str, Any]) -> bool:
        """Return True if the planned intervention has been cancelled.

        Cancellation is detected via:
        - etat = "A" (annulée), or
        - codeRemarque = "92" (AIP cancellation code, observed empirically).
        """
        etat = intr.get("etat")
        code_remarque = str(intr.get("codeRemarque", ""))
        return etat == "A" or code_remarque == "92"

    # ==========================================================================
    # Date helpers for planned interventions
    # ==========================================================================

    def _get_effective_dates(
        self, intr: dict[str, Any]
    ) -> tuple[datetime | None, datetime | None]:
        """Return the effective start and end dates for an interruption.

        For postponed interventions (etat = "R"), uses dateDebutReport/dateFinReport.
        Falls back to dateDebut/dateFin if report dates are absent.

        Returns: (effective_debut, effective_fin)
        """
        if intr.get("etat") == "R":
            debut = self._parse_dt(intr.get("dateDebutReport"))
            fin = self._parse_dt(intr.get("dateFinReport"))
            if debut:
                return debut, fin
        return (
            self._parse_dt(intr.get("dateDebut")),
            self._parse_dt(intr.get("dateFin")),
        )

    def _is_future_planned(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption is a planned intervention with a future start.

        Uses the report date for postponed interventions (etat = "R").
        """
        if not self._is_planned_intervention(intr):
            return False

        effective_debut, _ = self._get_effective_dates(intr)
        return self._is_date_in_future(effective_debut)

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
            intr for intr in self._get_interruptions()
            if not self._is_planned_intervention(intr)
            and self._is_outage_terminated(intr)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda i: self._parse_dt(i.get("dateFin"))
            or dt_util.utc_from_timestamp(0),
        )

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """Return the most relevant planned intervention (AIP), or None.

        Selection priority:
        1. Active planned intervention (main etat = "N", dateFin absent or future).
        2. Future planned intervention (effective dateDebut in the future).
        3. Any planned intervention, including terminated (fallback).
        """
        interruptions = self._get_interruptions()
        planned = [i for i in interruptions if self._is_planned_intervention(i)]
        if not planned:
            return None

        for p in planned:
            if self._is_outage_active(p):
                return p

        for p in planned:
            if self._is_future_planned(p):
                return p

        return planned[0]

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
        # Priority 1: active unplanned outage
        interruption = self._get_active_outage()
        if interruption:
            return interruption

        # Priority 2: terminated unplanned outage
        # Yield to an active or future AIP when one coexists.
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            planned_check = self._get_planned_intervention()
            if (
                not planned_check
                or self._is_aip_annulee(planned_check)
                or self._is_outage_terminated(planned_check)
            ):
                return terminated_outage
            # Fall through to Priority 3 — AIP state supersedes the past outage.

        # Priority 3: planned intervention
        interruption = self._get_planned_intervention()
        if interruption:
            return interruption

        # Priority 4: fallback to first available interruption
        interruptions = self._get_interruptions()
        if interruptions:
            return interruptions[0]

        return None
