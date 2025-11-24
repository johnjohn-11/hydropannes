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
            "model": "Info-pannes",
        }

    @property
    def is_on(self) -> bool:
        """Return true if there's an outage."""
        if not self.coordinator.data:
            return False

        etat = self.coordinator.data.get("etat")

        # N = panne en cours, A = service normal
        if etat == "N":
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

        # Séparer les pannes et interventions planifiées
        panne_en_cours = None
        intervention_planifiee = None
        
        for intr in interruptions:
            if intr.get("interruptionPlanifiee") is True:
                intervention_planifiee = intr
            else:
                panne_en_cours = intr

        # PRIORITÉ 1: Panne en cours (non planifiée)
        # PRIORITÉ 2: Intervention planifiée (si aucune panne en cours)
        active_interruption = panne_en_cours if panne_en_cours else intervention_planifiee
        
        # Fallback sur la première interruption
        if active_interruption is None:
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
            "model": "Info-pannes",
        }

    @property
    def is_on(self) -> bool:
        """Return true if there's a planned intervention."""
        if not self.coordinator.data:
            return False
        
        interruptions = self.coordinator.data.get("interruptions", [])
        
        if not interruptions:
            return False
        
        # Chercher une interruption planifiée
        for interruption in interruptions:
            if interruption.get("interruptionPlanifiee", False):
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
        """Return extra attributes."""

        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return {}

        # Séparer les pannes et interventions planifiées
        panne_en_cours = None
        intervention_planifiee = None
        
        for intr in interruptions:
            if intr.get("interruptionPlanifiee") is True:
                intervention_planifiee = intr
            else:
                panne_en_cours = intr

        # PRIORITÉ 1: Panne en cours (non planifiée)
        # PRIORITÉ 2: Intervention planifiée (si aucune panne en cours)
        active_interruption = panne_en_cours if panne_en_cours else intervention_planifiee
        
        # Fallback sur la première interruption
        if active_interruption is None:
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
