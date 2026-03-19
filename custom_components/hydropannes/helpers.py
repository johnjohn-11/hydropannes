"""Shared helper mixin for Hydro-Pannes sensors and binary sensors.

All business logic for interpreting the Hydro-Québec API response lives here.
Both HydroPannesSensorBase (sensor.py) and HydroPannesBinarySensorBase
(binary_sensor.py) inherit from HydroPannesHelperMixin, ensuring a single
source of truth for outage detection, date parsing, and priority logic.
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
        """Parse an ISO datetime string to localized datetime or return None."""
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
        """Check if a datetime is in the past."""
        if not date_value:
            return False
        return date_value <= dt_util.now()

    def _is_date_in_future(self, date_value: datetime | None) -> bool:
        """Check if a datetime is in the future."""
        if not date_value:
            return False
        return date_value > dt_util.now()

    # ==========================================================================
    # API data accessors
    # ==========================================================================

    def _get_main_etat(self) -> str | None:
        """Get the main 'etat' field from API response."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("etat")

    def _get_interruptions(self) -> list[dict[str, Any]]:
        """Get the list of interruptions from API response."""
        if not self.coordinator.data:
            return []
        result: list[dict[str, Any]] = self.coordinator.data.get("interruptions", [])
        return result

    # ==========================================================================
    # Interruption state checks
    # ==========================================================================

    def _is_outage_active(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption represents an active outage.

        An outage is considered ACTIVE if:
        - Main etat = "N" (outage state)
        - AND (no dateFin OR dateFin is in the future)

        Note: We ignore the interruption's own 'etat' field (T, C, etc.)
        as it doesn't reliably indicate active state.
        """
        main_etat = self._get_main_etat()
        if main_etat != "N":
            return False

        date_fin = self._parse_dt(intr.get("dateFin"))
        return not date_fin or self._is_date_in_future(date_fin)

    def _is_outage_terminated(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is terminated (power restored).

        An outage is TERMINATED if:
        - dateFin exists AND is in the past
        - AND etat != "R" (postponed interruptions are NOT terminated —
          their original dateFin is in the past but the work is rescheduled)
        """
        if intr.get("etat") == "R":
            return False
        date_fin = self._parse_dt(intr.get("dateFin"))
        return self._is_date_in_past(date_fin)

    def _is_planned_intervention(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is a planned intervention (AIP)."""
        result: bool = intr.get("interruptionPlanifiee", False)
        return result

    def _is_aip_annulee(self, intr: dict[str, Any]) -> bool:
        """Check if a planned intervention is cancelled.

        Detected via:
        - etat = "A" (annulée)
        - codeRemarque = "92" (annulation d'une AIP, observé empiriquement)
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
        """Return effective start/end dates for a planned intervention.

        If etat = "R" (postponed), use dateDebutReport/dateFinReport.
        Otherwise use dateDebut/dateFin.

        Returns: (effective_debut, effective_fin)
        """
        if intr.get("etat") == "R":
            debut = self._parse_dt(intr.get("dateDebutReport"))
            fin = self._parse_dt(intr.get("dateFinReport"))
            # Fall back to original if report dates are missing
            if debut:
                return debut, fin
        return (
            self._parse_dt(intr.get("dateDebut")),
            self._parse_dt(intr.get("dateFin")),
        )

    def _is_future_planned(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is a future planned intervention.

        Returns True if:
        - interruptionPlanifiee = True
        - AND effective dateDebut is in the future (uses report date if postponed)
        """
        if not self._is_planned_intervention(intr):
            return False

        effective_debut, _ = self._get_effective_dates(intr)
        return self._is_date_in_future(effective_debut)

    # ==========================================================================
    # Interruption selection (priority logic)
    # ==========================================================================

    def _get_active_outage(self) -> dict[str, Any] | None:
        """Get the first active non-planned outage.

        Returns the first interruption where:
        - interruptionPlanifiee = False
        - Main etat = "N"
        - No dateFin or dateFin in the future
        """
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr):
                continue
            if self._is_outage_active(intr):
                return intr
        return None

    def _get_terminated_outage(self) -> dict[str, Any] | None:
        """Get the most recent terminated non-planned outage.

        When multiple terminated interruptions exist (e.g. HQ splits a panne
        into sections), returns the one with the latest dateFin.
        """
        candidates = [
            intr for intr in self._get_interruptions()
            if not self._is_planned_intervention(intr)
            and self._is_outage_terminated(intr)
        ]
        if not candidates:
            return None
        # Return the one with the latest dateFin
        return max(
            candidates,
            key=lambda i: self._parse_dt(i.get("dateFin"))
            or dt_util.utc_from_timestamp(0),
        )

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """Get the most relevant planned intervention (AIP).

        Priority:
        1. Active planned (main etat = "N", no dateFin or dateFin in future)
        2. Future planned (effective dateDebut in future)
        3. Any planned intervention (including terminated — fallback)
        """
        interruptions = self._get_interruptions()
        planned = [i for i in interruptions if self._is_planned_intervention(i)]
        if not planned:
            return None

        # Priority 1: Active planned intervention
        for p in planned:
            if self._is_outage_active(p):
                return p

        # Priority 2: Future planned intervention (uses report date if postponed)
        for p in planned:
            if self._is_future_planned(p):
                return p

        # Priority 3: Any planned (including terminated)
        return planned[0]

    def _get_current_interruption(self) -> dict[str, Any] | None:
        """Get the most relevant interruption for displaying sensor data.

        Priority logic:
        1. Active non-planned outage (ongoing — power is out)
        2. Terminated non-planned outage (recently finished — "Service rétabli")
           UNLESS a non-cancelled, non-terminated AIP also exists (AIP takes over)
        3. Planned intervention (active, future, or terminated)
        4. First interruption in list (fallback)
        """
        # Priority 1: Active non-planned outage
        interruption = self._get_active_outage()
        if interruption:
            return interruption

        # Priority 2: Terminated non-planned outage
        # But yield to an active/future AIP if one exists simultaneously
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            planned_check = self._get_planned_intervention()
            if not planned_check or self._is_aip_annulee(planned_check) or self._is_outage_terminated(planned_check):
                return terminated_outage
            # Fall through to Priority 3 — show the AIP state instead

        # Priority 3: Planned intervention
        interruption = self._get_planned_intervention()
        if interruption:
            return interruption

        # Priority 4: Fallback to first interruption if any
        interruptions = self._get_interruptions()
        if interruptions:
            return interruptions[0]

        return None
