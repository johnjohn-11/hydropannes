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

        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data

        etat = data.get("etat")

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

        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data

        interruptions = data.get("interruptions", [])
        if not interruptions:
            return {}

        # Chercher la panne EN COURS (non planifiée)
        panne_en_cours = None
        for intr in interruptions:
            if not intr.get("interruptionPlanifiee", False):
                panne_en_cours = intr
                break

        # Si aucune panne en cours, prendre la première disponible
        if panne_en_cours is None:
            panne_en_cours = interruptions[0]

        return {
            "dateDebut": panne_en_cours.get("dateDebut"),
            "dateFin": panne_en_cours.get("dateFin"),
            "dateFinEstimeeMax": panne_en_cours.get("dateFinEstimeeMax"),
            "etat": panne_en_cours.get("etat"),
            "planifie": panne_en_cours.get("interruptionPlanifiee"),
            "codeIntervention": panne_en_cours.get("codeIntervention"),
            "niveauUrgence": panne_en_cours.get("niveauUrgence"),
            "nbClient": panne_en_cours.get("nbClient"),
            "codeCause": panne_en_cours.get("codeCause"),
            "codeMunicipal": panne_en_cours.get("codeMunicipal"),
            "dureePrevu": panne_en_cours.get("dureePrevu"),
            "typeFinPrevue": panne_en_cours.get("typeFinPrevue"),
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
        
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
            
        interruptions = data.get("interruptions", [])
        
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

        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data

        interruptions = data.get("interruptions", [])
        if not interruptions:
            return {}

        # Chercher l'intervention PLANIFIÉE
        intervention_planifiee = None
        for intr in interruptions:
            if intr.get("interruptionPlanifiee", False):
                intervention_planifiee = intr
                break

        # Si aucune intervention planifiée, prendre la première disponible
        if intervention_planifiee is None:
            intervention_planifiee = interruptions[0]

        return {
            "dateDebut": intervention_planifiee.get("dateDebut"),
            "dateFin": intervention_planifiee.get("dateFin"),
            "dateFinEstimeeMax": intervention_planifiee.get("dateFinEstimeeMax"),
            "etat": intervention_planifiee.get("etat"),
            "planifie": intervention_planifiee.get("interruptionPlanifiee"),
            "codeIntervention": intervention_planifiee.get("codeIntervention"),
            "niveauUrgence": intervention_planifiee.get("niveauUrgence"),
            "nbClient": intervention_planifiee.get("nbClient"),
            "codeCause": intervention_planifiee.get("codeCause"),
            "codeMunicipal": intervention_planifiee.get("codeMunicipal"),
            "dureePrevu": intervention_planifiee.get("dureePrevu"),
            "typeFinPrevue": intervention_planifiee.get("typeFinPrevue"),
            "attribution": "Données fournies par Hydro-Québec",
        }
