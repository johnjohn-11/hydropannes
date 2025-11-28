"""Support for Hydro-Pannes binary sensors."""
from __future__ import annotations

import logging
from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_NOM_LIEU

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]

    binary_sensors = [
        HydroPannesEtatServiceBinarySensor(coordinator, entry, nom_lieu),
        HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry, nom_lieu),
    ]

    async_add_entities(binary_sensors)


class HydroPannesEtatServiceBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for Hydro-Pannes service status."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
        self._attr_name = "État du service"
        self._attr_unique_id = f"{entry.entry_id}_etat_service"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"HydroPannes {self._nom_lieu}",
            "manufacturer": "HQ",
            "model": "Info-pannes",
        }

    def _is_interruption_terminated(self, intr: dict[str, Any]) -> bool:
        if not intr:
            return False
        if intr.get("dateFin"):
            return True
        if intr.get("etat") in ("C", "T"):
            return True
        return False

    @property
    def is_on(self) -> bool:
        """Return true if there's an outage (service problem)."""
        if not self.coordinator.data:
            return False

        etat = self.coordinator.data.get("etat")
        # Quick test: if main state not 'N', there is no outage
        if etat != "N":
            return False

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return False

        # find a non-planned interruption that is not terminated
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                continue
            if self._is_interruption_terminated(intr):
                continue
            # active non-planned outage found
            return True

        return False

    @property
    def icon(self):
        """Return the icon."""
        if self.is_on:
            return "mdi:power-plug-off"
        return "mdi:power-plug"

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return {}

        # Priority: active non-planned outage first, otherwise planned, otherwise first record
        active = None
        planned = None
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                if planned is None:
                    planned = intr
            else:
                # pick first non-planned that is not terminated
                if not self._is_interruption_terminated(intr) and active is None:
                    active = intr
                # if none active, keep the first non-planned as fallback
                if active is None and planned is None and intr is not None:
                    # nothing to do here; keep scanning
                    pass

        active_interruption = active if active else planned
        if not active_interruption:
            active_interruption = interruptions[0]

        return {
            "dateDebut": active_interruption.get("dateDebut"),
            "dateFin": active_interruption.get("dateFin"),
            "dateFinEstimeeMax": active_interruption.get("dateFinEstimeeMax"),
            "etat": active_interruption.get("etat"),
            "planifie": active_interruption.get("interruptionPlanifiee"),
            "codeIntervention": active_interruption.get("codeIntervention"),
            "niveauUrgence": active_interruption.get("niveauUrgence"),
            "nbClient": active_interruption.get("nbClient"),
            "codeCause": active_interruption.get("codeCause"),
            "codeMunicipal": active_interruption.get("codeMunicipal"),
            "dureePrevu": active_interruption.get("dureePrevu"),
            "typeFinPrevue": active_interruption.get("typeFinPrevue"),
            "attribution": "Données fournies par Hydro-Québec",
        }


class HydroPannesInterventionPlanifieeBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for planned intervention status."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
        self._attr_name = "Intervention planifiée"
        self._attr_unique_id = f"{entry.entry_id}_intervention_planifiee"
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"HydroPannes {self._nom_lieu}",
            "manufacturer": "HQ",
            "model": "Info-pannes",
        }

    @property
    def is_on(self) -> bool:
        """Return true if there's a planned intervention."""
        if not self.coordinator.data:
            return False

        interruptions = self.coordinator.data.get("interruptions", [])
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                return True
        return False

    @property
    def icon(self):
        """Return the icon."""
        if self.is_on:
            return "mdi:calendar-clock"
        return "mdi:calendar-check"

    @property
    def extra_state_attributes(self):
        """Return extra attributes (from the planned interruption even if a non-planned outage exists)."""
        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return {}

        # find the planned interruption (first active planned otherwise most relevant planned)
        planned = None
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                planned = intr
                # prefer active planned (no dateFin and not etat C/T)
                if not intr.get("dateFin") and intr.get("etat") != "C" and intr.get("etat") != "T":
                    break

        if not planned:
            return {}

        return {
            "dateDebut": planned.get("dateDebut"),
            "dateFin": planned.get("dateFin"),
            "dateFinEstimeeMax": planned.get("dateFinEstimeeMax"),
            "etat": planned.get("etat"),
            "planifie": planned.get("interruptionPlanifiee"),
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
