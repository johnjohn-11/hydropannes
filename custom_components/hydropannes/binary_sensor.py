"""Support for Hydro-Pannes binary sensors."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NOM_LIEU, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes binary sensors."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]

    binary_sensors = [
        HydroPannesEtatServiceBinarySensor(coordinator, entry, nom_lieu),
        HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry, nom_lieu),
    ]

    async_add_entities(binary_sensors)


class HydroPannesEtatServiceBinarySensor(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator], BinarySensorEntity
):
    """
    Binary sensor for Hydro-Pannes service status.

    Logic:
    ------
    Returns ON (True) if:
      - Main etat = "N" (outage detected)
      - AND there is an active non-planned interruption (no dateFin)

    Returns OFF (False) if:
      - Main etat = "A" (service active)
      - OR all non-planned interruptions have dateFin (power restored)

    Attributes use priority logic:
      - Priority 1: active non-planned outage
      - Priority 2: planned intervention (if no active outage)
    """

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
        self._attr_name = "État du service"
        self._attr_unique_id = f"{entry.entry_id}_etat_service"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HydroPannes {self._nom_lieu}",
            manufacturer=None,
            model="Info-pannes",
        )

    def _is_interruption_terminated(self, intr: dict[str, Any]) -> bool:
        """
        Check if an interruption is terminated.

        An interruption is terminated if:
        - dateFin is present, OR
        - etat is 'C' (Completed) or 'T' (Terminated)
        """
        if not intr:
            return False
        if intr.get("dateFin"):
            return True
        if intr.get("etat") in ("C", "T"):
            return True
        return False

    def _get_active_outage(self) -> dict[str, Any] | None:
        """
        Get the first active non-planned outage.

        Returns the first interruption where:
        - interruptionPlanifiee = False
        - Not terminated (no dateFin, etat not in C/T)
        """
        if not self.coordinator.data:
            return None

        interruptions = self.coordinator.data.get("interruptions", [])
        for intr in interruptions:
            # Skip planned interventions
            if intr.get("interruptionPlanifiee", False):
                continue
            # Skip terminated interruptions
            if self._is_interruption_terminated(intr):
                continue
            return intr
        return None

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """
        Get the most relevant planned intervention.

        Prefers active (not terminated) planned interventions.
        """
        if not self.coordinator.data:
            return None

        interruptions = self.coordinator.data.get("interruptions", [])
        planned = None
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                # Prefer active planned (not terminated)
                if not self._is_interruption_terminated(intr):
                    return intr
                # Keep first planned as fallback
                if planned is None:
                    planned = intr
        return planned

    @property
    def is_on(self) -> bool:
        """
        Return true if there's an active outage (service problem).

        ON condition:
        - Main etat = "N"
        - AND at least one active non-planned interruption exists
        """
        if not self.coordinator.data:
            return False

        etat = self.coordinator.data.get("etat")

        # If main state is not "N", there is no outage
        if etat != "N":
            return False

        # Check for active non-planned outage
        active_outage = self._get_active_outage()
        return active_outage is not None

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        if self.is_on:
            return "mdi:power-plug-off"
        return "mdi:power-plug"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Return extra attributes from the active interruption.

        Priority for attributes:
        1. Active non-planned outage
        2. Planned intervention
        3. First interruption in list
        """
        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
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


class HydroPannesInterventionPlanifieeBinarySensor(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator], BinarySensorEntity
):
    """
    Binary sensor for planned intervention status.

    Logic:
    ------
    Returns ON (True) if:
      - At least one interruption with interruptionPlanifiee = True exists

    Returns OFF (False) if:
      - No planned intervention exists

    Note: This sensor shows ON even if the planned intervention is terminated,
    as it indicates that a planned intervention record exists in the data.
    """

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
        self._attr_name = "Intervention planifiée"
        self._attr_unique_id = f"{entry.entry_id}_intervention_planifiee"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HydroPannes {self._nom_lieu}",
            manufacturer=None,
            model="Info-pannes",
        )

    def _is_interruption_terminated(self, intr: dict[str, Any]) -> bool:
        """
        Check if an interruption is terminated.

        An interruption is terminated if:
        - dateFin is present, OR
        - etat is 'C' (Completed) or 'T' (Terminated)
        """
        if not intr:
            return False
        if intr.get("dateFin"):
            return True
        if intr.get("etat") in ("C", "T"):
            return True
        return False

    @property
    def is_on(self) -> bool:
        """
        Return true if there's a planned intervention.

        ON if at least one interruption has interruptionPlanifiee = True
        """
        if not self.coordinator.data:
            return False

        interruptions = self.coordinator.data.get("interruptions", [])
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
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
        """
        Return extra attributes from the planned intervention.

        Only returns attributes if a planned intervention exists.
        Prefers active planned over terminated planned.
        """
        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return {}

        # Find the most relevant planned intervention
        planned = None
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                # Prefer active planned (not terminated)
                if not self._is_interruption_terminated(intr):
                    planned = intr
                    break
                # Keep first planned as fallback
                if planned is None:
                    planned = intr

        if not planned:
            return {}

        return {
            "dateDebut": planned.get("dateDebut"),
            "dateFin": planned.get("dateFin"),
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
