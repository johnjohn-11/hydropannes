"""Support for Hydro-Pannes binary sensors."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
        self._attr_name = "État du Service"
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
            "model": "Surveillance de pannes",
        }

    @property
    def is_on(self) -> bool:
        """Return true if there's an outage."""
        if not self.coordinator.data:
            return False
        
        etat = self.coordinator.data.get("etat")

        # Si etat n'est pas défini, on considère qu'il n'y a pas de panne
        if etat is None:
            return False

        # A = Aucun problème
        if etat == "A":
            return False

        # N = Panne active
        if etat == "N":
            return True

        # Tout autre état = par défaut pas de panne
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

        # Panne non planifiée = priorité
        active_outage = None
        for interruption in interruptions:
            if not interruption.get("interruptionPlanifiee", False):
                active_outage = interruption
                break

        # Sinon prendre la première interruption
        if active_outage is None:
            active_outage = interruptions[0]

        return {
            "dateDebut": active_outage.get("dateDebut"),
            "dateFin": active_outage.get("dateFin"),
            "etat": active_outage.get("etat"),
            "dateFinEstimeeMin": active_outage.get("dateFinEstimeeMin"),
            "dateFinEstimeeMax": active_outage.get("dateFinEstimeeMax"),
            "codeIntervention": active_outage.get("codeIntervention"),
            "niveauUrgence": active_outage.get("niveauUrgence"),
            "nbClient": active_outage.get("nbClient"),
            "codeCause": active_outage.get("codeCause"),
            "codeMunicipal": active_outage.get("codeMunicipal"),
            "datePublication": active_outage.get("datePublication"),
            "codeRemarque": active_outage.get("codeRemarque"),
            "dureePrevu": active_outage.get("dureePrevu"),
            "probabilite": active_outage.get("probabilite"),
            "interruptionPlanifiee": active_outage.get("interruptionPlanifiee"),
            "attribution": "Données fournies par Hydro-Québec",
        }


class HydroPannesInterventionPlanifieeBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for planned intervention status."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
        self._attr_name = "Intervention Planifiée"
        self._attr_unique_id = f"{entry.entry_id}_intervention_planifiee"
        self._attr_has_entity_name = True

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"HydroPannes {self._nom_lieu}",
            "manufacturer": "HQ",
            "model": "Surveillance des pannes",
        }

    @property
    def is_on(self) -> bool:
        """Return true if there's a planned intervention."""
        if not self.coordinator.data:
            return False
        
        interruptions = self.coordinator.data.get("interruptions", [])
        
        if not interruptions or len(interruptions) == 0:
            return False
        
        interruption = interruptions[0]
        
        return interruption.get("interruptionPlanifiee", False)

    @property
    def icon(self):
        """Return the icon."""
        if self.is_on:
            return "mdi:calendar-clock"
        return "mdi:calendar-check"
