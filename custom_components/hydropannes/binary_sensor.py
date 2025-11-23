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
    _LOGGER.debug("Setting up Hydro-Pannes binary sensors")
    
    coordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]
    
    _LOGGER.debug(f"Coordinator data type: {type(coordinator.data)}")
    _LOGGER.debug(f"Coordinator data: {coordinator.data}")
    
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
        try:
            _LOGGER.debug(f"EtatService - Coordinator data available: {self.coordinator.data is not None}")
            
            if not self.coordinator.data:
                _LOGGER.warning("EtatService - No coordinator data")
                return False

            # Hydro API retourne une liste
            _LOGGER.debug(f"EtatService - Data type: {type(self.coordinator.data)}")
            data = self.coordinator.data[0]
            _LOGGER.debug(f"EtatService - First element: {data}")

            etat = data.get("etat")
            _LOGGER.debug(f"EtatService - État: {etat}")

            if etat == "A":
                return False

            if etat == "N":
                return True

            return False
        except Exception as e:
            _LOGGER.error(f"EtatService - Error in is_on: {e}", exc_info=True)
            return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        available = self.coordinator.last_update_success and self.coordinator.data is not None
        _LOGGER.debug(f"EtatService - Available: {available}")
        return available

    @property
    def icon(self):
        """Return the icon."""
        if self.is_on:
            return "mdi:power-plug-off"
        return "mdi:power-plug"

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        try:
            if not self.coordinator.data:
                return {}

            # Hydro-Pannes retourne une LISTE
            data = self.coordinator.data[0]

            interruptions = data.get("interruptions", [])
            if not interruptions:
                return {}

            # On préfère une interruption non planifiée
            active = None
            for intr in interruptions:
                if not intr.get("interruptionPlanifiee", False):
                    active = intr
                    break

            # sinon on prend la première (planifiée)
            if active is None:
                active = interruptions[0]

            return {
                "dateDebut": active.get("dateDebut"),
                "dateFin": active.get("dateFin"),
                "etat": active.get("etat"),
                "planifie": active.get("interruptionPlanifiee"),
                "niveauUrgence": active.get("niveauUrgence"),
                "nbClient": active.get("nbClient"),
                "codeCause": active.get("codeCause"),
                "codeMunicipal": active.get("codeMunicipal"),
                "dureePrevu": active.get("dureePrevu"),
                "typeFinPrevue": active.get("typeFinPrevue"),
                "attribution": "Données fournies par Hydro-Québec",
            }
        except Exception as e:
            _LOGGER.error(f"EtatService - Error in extra_state_attributes: {e}", exc_info=True)
            return {}


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
        try:
            _LOGGER.debug(f"InterventionPlanifiee - Coordinator data available: {self.coordinator.data is not None}")
            
            if not self.coordinator.data:
                _LOGGER.warning("InterventionPlanifiee - No coordinator data")
                return False
            
            # Accès cohérent : data est une liste
            data = self.coordinator.data[0]
            interruptions = data.get("interruptions", [])
            
            _LOGGER.debug(f"InterventionPlanifiee - Found {len(interruptions)} interruptions")
            
            if not interruptions or len(interruptions) == 0:
                return False
            
            interruption = interruptions[0]
            planifiee = interruption.get("interruptionPlanifiee", False)
            
            _LOGGER.debug(f"InterventionPlanifiee - Is planned: {planifiee}")
            
            return planifiee
        except Exception as e:
            _LOGGER.error(f"InterventionPlanifiee - Error in is_on: {e}", exc_info=True)
            return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        available = self.coordinator.last_update_success and self.coordinator.data is not None
        _LOGGER.debug(f"InterventionPlanifiee - Available: {available}")
        return available

    @property
    def icon(self):
        """Return the icon."""
        if self.is_on:
            return "mdi:calendar-clock"
        return "mdi:calendar-check"
