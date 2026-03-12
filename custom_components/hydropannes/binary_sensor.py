"""Support for Hydro-Pannes binary sensors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_NOM_LIEU, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes binary sensors."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]

    binary_sensors: list[HydroPannesBinarySensorBase] = [
        HydroPannesEtatServiceBinarySensor(coordinator, entry, nom_lieu),
        HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry, nom_lieu),
    ]

    async_add_entities(binary_sensors)


class HydroPannesBinarySensorBase(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator], BinarySensorEntity
):
    """Base class for Hydro-Pannes binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HydroPannes {self._nom_lieu}",
            manufacturer=None,
            model="Info-pannes",
        )

    # ==========================================================================
    # Helper methods (same logic as sensor.py)
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

    def _is_outage_active(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption represents an active outage."""
        main_etat = self._get_main_etat()
        if main_etat != "N":
            return False

        date_fin = self._parse_dt(intr.get("dateFin"))
        return not date_fin or self._is_date_in_future(date_fin)

    def _is_outage_terminated(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is terminated (power restored).

        Postponed interventions (etat = "R") are NOT terminated even if
        their original dateFin is in the past.
        """
        if intr.get("etat") == "R":
            return False
        date_fin = self._parse_dt(intr.get("dateFin"))
        return self._is_date_in_past(date_fin)

    def _is_planned_intervention(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is a planned intervention."""
        result: bool = intr.get("interruptionPlanifiee", False)
        return result

    def _get_active_outage(self) -> dict[str, Any] | None:
        """Get the first active non-planned outage."""
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr):
                continue
            if self._is_outage_active(intr):
                return intr
        return None

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """Get the most relevant planned intervention."""
        interruptions = self._get_interruptions()
        planned = [i for i in interruptions if self._is_planned_intervention(i)]
        if not planned:
            return None

        # Priority 1: Active planned intervention
        for p in planned:
            if self._is_outage_active(p):
                return p

        # Priority 2: Future planned intervention (use report date if postponed)
        for p in planned:
            if p.get("etat") == "R":
                date_debut = self._parse_dt(p.get("dateDebutReport")) or self._parse_dt(p.get("dateDebut"))
            else:
                date_debut = self._parse_dt(p.get("dateDebut"))
            if self._is_date_in_future(date_debut):
                return p

        # Priority 3: Any planned (including terminated)
        return planned[0]


class HydroPannesEtatServiceBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor for Hydro-Pannes service status."""

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "État du service"
        self._attr_unique_id = f"{entry.entry_id}_etat_service"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        """Return true if there's an active outage (service problem)."""
        if not self.coordinator.data:
            return None

        main_etat = self._get_main_etat()

        # If main state is not "N", there is no outage
        if main_etat != "N":
            return False

        # Check for active non-planned outage
        active_outage = self._get_active_outage()
        if active_outage:
            return True

        # Also check if there's an active planned intervention causing the outage
        planned = self._get_planned_intervention()
        if planned and self._is_outage_active(planned):
            return True

        # Main etat is "N" but no active interruption found
        # This could be a transitional state, return True to be safe
        return True

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        if self.is_on:
            return "mdi:power-plug-off"
        return "mdi:power-plug"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes from the active interruption."""
        if not self.coordinator.data:
            return {}

        interruptions = self._get_interruptions()
        if not interruptions:
            return {}

        # Select interruption based on priority
        active_interruption = self._get_active_outage()
        if not active_interruption:
            active_interruption = self._get_planned_intervention()
        if not active_interruption:
            active_interruption = interruptions[0]

        return {
            "dateDebut": active_interruption.get("dateDebut"),
            "dateFin": active_interruption.get("dateFin"),
            "dateDebutReport": active_interruption.get("dateDebutReport"),
            "dateFinReport": active_interruption.get("dateFinReport"),
            "dateFinEstimeeMax": active_interruption.get("dateFinEstimeeMax"),
            "etat": active_interruption.get("etat"),
            "interruptionPlanifiee": active_interruption.get("interruptionPlanifiee"),
            "codeIntervention": active_interruption.get("codeIntervention"),
            "niveauUrgence": active_interruption.get("niveauUrgence"),
            "nbClient": active_interruption.get("nbClient"),
            "codeCause": active_interruption.get("codeCause"),
            "codeMunicipal": active_interruption.get("codeMunicipal"),
            "dureePrevu": active_interruption.get("dureePrevu"),
            "typeFinPrevue": active_interruption.get("typeFinPrevue"),
            "attribution": "Données fournies par Hydro-Québec",
        }


class HydroPannesInterventionPlanifieeBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor for planned intervention status."""

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Intervention planifiée"
        self._attr_unique_id = f"{entry.entry_id}_intervention_planifiee"

    @property
    def is_on(self) -> bool | None:
        """Return true if there's an active or upcoming planned intervention."""
        if not self.coordinator.data:
            return None

        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr) and not self._is_outage_terminated(
                intr
            ):
                return True

        return False

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        if self.is_on:
            return "mdi:calendar-clock"
        return "mdi:calendar-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes from the planned intervention."""
        if not self.coordinator.data:
            return {}

        interruptions = self._get_interruptions()
        if not interruptions:
            return {}

        # Find the most relevant planned intervention (not terminated)
        planned = None
        for intr in interruptions:
            if self._is_planned_intervention(intr) and not self._is_outage_terminated(
                intr
            ):
                planned = intr
                break

        if not planned:
            return {}

        return {
            "dateDebut": planned.get("dateDebut"),
            "dateFin": planned.get("dateFin"),
            "dateDebutReport": planned.get("dateDebutReport"),
            "dateFinReport": planned.get("dateFinReport"),
            "dateFinEstimeeMax": planned.get("dateFinEstimeeMax"),
            "etat": planned.get("etat"),
            "interruptionPlanifiee": planned.get("interruptionPlanifiee"),
            "codeIntervention": planned.get("codeIntervention"),
            "niveauUrgence": planned.get("niveauUrgence"),
            "nbClient": planned.get("nbClient"),
            "codeCause": planned.get("codeCause"),
            "codeMunicipal": planned.get("codeMunicipal"),
            "dureePrevu": planned.get("dureePrevu"),
            "typeFinPrevue": planned.get("typeFinPrevue"),
            "datePublication": planned.get("datePublication"),
            "codeRemarque": planned.get("codeRemarque"),
            "probabilite": planned.get("probabilite"),
            "attribution": "Données fournies par Hydro-Québec",
        }
