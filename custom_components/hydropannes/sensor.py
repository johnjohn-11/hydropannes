"""Support for Hydro-Pannes sensors."""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_NOM_LIEU,
    CAUSE_CODES,
    INTERVENTION_CODES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]
    
    sensors = [
        HydroPannesInfoPannesSensor(coordinator, entry, nom_lieu),
        HydroPannesNiveauUrgenceSensor(coordinator, entry, nom_lieu),
        HydroPannesAdressesToucheesSensor(coordinator, entry, nom_lieu),
        HydroPannesDebutSensor(coordinator, entry, nom_lieu),
        HydroPannesFinEstimeeSensor(coordinator, entry, nom_lieu),
        HydroPannesStatutInterventionSensor(coordinator, entry, nom_lieu),
        HydroPannesCauseSensor(coordinator, entry, nom_lieu),
        HydroPannesDureeSensor(coordinator, entry, nom_lieu),
        HydroPannesDureeAvantRetablissementSensor(coordinator, entry, nom_lieu),
        HydroPannesDerniereMAJSensor(coordinator, entry, nom_lieu),
        HydroPannesLieuConsoSensor(coordinator, entry, nom_lieu),
    ]
    
    async_add_entities(sensors)


class HydroPannesSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Hydro-Pannes sensors."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
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

    def _get_interruption(self):
        """Get first interruption if exists."""
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
            
        if data and "interruptions" in data:
            interruptions = data["interruptions"]
            if interruptions and len(interruptions) > 0:
                return interruptions[0]
        return None

    def _get_active_outage(self):
        """Get the first active outage (not planned intervention)."""
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
            
        if not data or "interruptions" not in data:
            return None
        
        interruptions = data["interruptions"]
        for interruption in interruptions:
            if not interruption.get("interruptionPlanifiee", False):
                return interruption
        
        return None

    def _get_planned_intervention(self):
        """Get the first planned intervention."""
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
            
        if not data or "interruptions" not in data:
            return None
        
        interruptions = data["interruptions"]
        for interruption in interruptions:
            if interruption.get("interruptionPlanifiee", False):
                return interruption
        
        return None


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """Sensor for service status info."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Info Pannes"
        self._attr_unique_id = f"{entry.entry_id}_info_pannes"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self):
        """Return the state."""
        if not self.coordinator.data:
            return "Indisponible"
        
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
        
        etat = data.get("etat")
        interruptions = data.get("interruptions", [])
        
        # No interruptions
        if not interruptions or len(interruptions) == 0:
            if etat == "A":
                return "Aucune panne détectée"
            else:
                return "Indisponible"
        
        # Séparer les pannes et interventions planifiées
        active_outage = None
        planned = None
        
        for interruption in interruptions:
            if interruption.get("interruptionPlanifiee") is True:
                planned = interruption
            else:
                active_outage = interruption
        
        # PRIORITY 1: Panne en cours (non planifiée)
        if active_outage:
            outage_etat = active_outage.get("etat")
            
            if outage_etat in ["C", "P"]:
                return "Panne en cours"
            
            if outage_etat == "T" or active_outage.get("dateFin"):
                return "Courant rétabli"
        
        # PRIORITY 2: Intervention planifiée
        if planned:
            planned_etat = planned.get("etat")
            
            # Terminée
            if planned_etat == "T" or (planned.get("dateFin") and etat == "A"):
                return "Intervention planifiée terminée"
            
            # En cours
            if planned_etat == "C" or etat == "N":
                return "Intervention planifiée en cours"
            
            # À venir
            if planned_etat == "P" and etat == "A":
                return "Interruption planifiée à venir"
            
            # Check date for future intervention
            if etat == "A" and planned.get("dateDebut") and not planned.get("dateFin"):
                try:
                    date_debut = datetime.fromisoformat(planned["dateDebut"].replace("Z", "+00:00"))
                    maintenant = dt_util.now()
                    
                    if date_debut > maintenant:
                        return "Interruption planifiée à venir"
                except Exception:
                    pass
        
        # Default
        if etat == "A":
            return "Aucune panne détectée"
        
        return "Indisponible"

    @property
    def icon(self):
        """Return the icon."""
        state = self.native_value
        if state == "Aucune panne détectée":
            return "mdi:check-circle"
        elif state in ["Courant rétabli", "Intervention planifiée terminée"]:
            return "mdi:check-circle-outline"
        elif state in ["Interruption planifiée à venir", "Intervention planifiée en cours"]:
            return "mdi:calendar-clock"
        elif state == "Panne en cours":
            return "mdi:alert-circle"
        return "mdi:help-circle"

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
        
        # Séparer les pannes et interventions planifiées
        panne_en_cours = None
        intervention_planifiee = None
        
        for interruption in interruptions:
            if interruption.get("interruptionPlanifiee") is True:
                intervention_planifiee = interruption
            else:
                panne_en_cours = interruption
        
        # Priorité à la panne en cours
        active_interruption = panne_en_cours if panne_en_cours else intervention_planifiee
        
        if not active_interruption:
            active_interruption = interruptions[0]
        
        return {
            "dateDebut": active_interruption.get("dateDebut"),
            "dateFin": active_interruption.get("dateFin"),
            "etat": active_interruption.get("etat"),
            "dateFinEstimeeMin": active_interruption.get("dateFinEstimeeMin"),
            "dateFinEstimeeMax": active_interruption.get("dateFinEstimeeMax"),
            "codeIntervention": active_interruption.get("codeIntervention"),
            "niveauUrgence": active_interruption.get("niveauUrgence"),
            "nbClient": active_interruption.get("nbClient"),
            "codeCause": active_interruption.get("codeCause"),
            "codeMunicipal": active_interruption.get("codeMunicipal"),
            "datePublication": active_interruption.get("datePublication"),
            "codeRemarque": active_interruption.get("codeRemarque"),
            "dureePrevu": active_interruption.get("dureePrevu"),
            "probabilite": active_interruption.get("probabilite"),
            "interruptionPlanifiee": active_interruption.get("interruptionPlanifiee"),
            "attribution": "Données fournies par Hydro-Québec",
        }


class HydroPannesDerniereMAJSensor(HydroPannesSensorBase):
    """Sensor for last update time."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Dernière MAJ"
        self._attr_unique_id = f"{entry.entry_id}_derniere_maj"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = "timestamp"

    @property
    def native_value(self):
        """Return the state as ISO timestamp."""
        interruption = self._get_interruption()
        
        if interruption and "datePublication" in interruption:
            try:
                date_obj = datetime.fromisoformat(interruption["datePublication"].replace("Z", "+00:00"))
                return date_obj
            except Exception:
                pass
        
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
            
        if data and "date" in data:
            date_str = data["date"]
            try:
                date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return date_obj
            except Exception:
                pass
        
        return None


class HydroPannesAdressesToucheesSensor(HydroPannesSensorBase):
    """Sensor for affected clients."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Clients Affectés"
        self._attr_unique_id = f"{entry.entry_id}_adresses_touchees"
        self._attr_native_unit_of_measurement = "clients"
        self._attr_icon = "mdi:account-multiple"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage:
            return 0
        
        return outage.get("nbClient", 0)


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor for outage start time."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Début"
        self._attr_unique_id = f"{entry.entry_id}_debut"
        self._attr_icon = "mdi:clock-start"
        self._attr_device_class = "timestamp"

    @property
    def native_value(self):
        """Return the state as ISO timestamp."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage or "dateDebut" not in outage:
            return None
        
        try:
            date_obj = datetime.fromisoformat(outage["dateDebut"].replace("Z", "+00:00"))
            return date_obj
        except Exception:
            return None


class HydroPannesFinEstimeeSensor(HydroPannesSensorBase):
    """Sensor for estimated end time."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Fin Estimée"
        self._attr_unique_id = f"{entry.entry_id}_fin_estimee"
        self._attr_icon = "mdi:clock-end"
        self._attr_device_class = "timestamp"

    @property
    def native_value(self):
        """Return the state as ISO timestamp."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage:
            return None
        
        # Priority 1: dateFin (actual end time)
        if "dateFin" in outage and outage.get("dateFin"):
            try:
                date_obj = datetime.fromisoformat(outage["dateFin"].replace("Z", "+00:00"))
                return date_obj
            except Exception:
                pass
        
        # Priority 2: dateFinEstimeeMax (estimated end time)
        if "dateFinEstimeeMax" in outage and outage.get("dateFinEstimeeMax"):
            try:
                date_obj = datetime.fromisoformat(outage["dateFinEstimeeMax"].replace("Z", "+00:00"))
                return date_obj
            except Exception:
                pass
        
        return None


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """Sensor for intervention status."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Statut Intervention"
        self._attr_unique_id = f"{entry.entry_id}_statut_intervention"
        self._attr_icon = "mdi:account-hard-hat"

    @property
    def native_value(self):
        """Return the state."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage:
            return "Aucune intervention"
        
        # Si l'intervention est terminée
        if outage.get("dateFin") or outage.get("etat") == "T":
            return "Intervention terminée"
        
        code = outage.get("codeIntervention")
        if code:
            return INTERVENTION_CODES.get(code, "Inconnu")
        
        return "Aucune intervention"


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor for urgency level."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Niveau Urgence"
        self._attr_unique_id = f"{entry.entry_id}_niveau_urgence"
        self._attr_icon = "mdi:alert-octagon"

    @property
    def native_value(self):
        """Return the state."""
        interruption = self._get_interruption()
        
        if not interruption or "niveauUrgence" not in interruption:
            return "N/A"
        
        niveau = interruption.get("niveauUrgence")
        
        if niveau == "P":
            return "Panne"
        elif niveau == "N":
            return "Panne majeure"
        else:
            return "Inconnu"


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """Sensor for outage cause."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Cause"
        self._attr_unique_id = f"{entry.entry_id}_cause"
        self._attr_icon = "mdi:help-circle-outline"

    @property
    def native_value(self):
        """Return the state."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage:
            return "Aucune panne"
        
        code = str(outage.get("codeCause", ""))
        if code:
            cause_text = CAUSE_CODES.get(code, "Inconnu")
            return f"{cause_text} ({code})"
        
        return "Aucune panne"


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor for outage duration."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée"
        self._attr_unique_id = f"{entry.entry_id}_duree"
        self._attr_native_unit_of_measurement = "heures"
        self._attr_icon = "mdi:timer-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage or "dateDebut" not in outage:
            return 0
        
        try:
            date_debut = datetime.fromisoformat(outage["dateDebut"].replace("Z", "+00:00"))
            
            if outage.get("dateFin"):
                date_fin = datetime.fromisoformat(outage["dateFin"].replace("Z", "+00:00"))
                duree = (date_fin - date_debut).total_seconds() / 3600
            else:
                maintenant = dt_util.now()
                duree = (maintenant - date_debut).total_seconds() / 3600
            
            return round(duree, 1)
        except Exception:
            return 0


class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor for time until power restoration."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée Avant Rétablissement"
        self._attr_unique_id = f"{entry.entry_id}_duree_avant_retablissement"
        self._attr_native_unit_of_measurement = "heures"
        self._attr_icon = "mdi:timer-sand"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state."""
        # Priorité à la panne en cours
        outage = self._get_active_outage()
        
        # Si pas de panne en cours, prendre l'intervention planifiée
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage:
            return 0
        
        # Si terminé, retourner 0
        if outage.get("dateFin") or outage.get("etat") == "T":
            return 0
        
        if "dateFinEstimeeMax" not in outage:
            return 0
        
        try:
            date_fin_estimee = datetime.fromisoformat(outage["dateFinEstimeeMax"].replace("Z", "+00:00"))
            maintenant = dt_util.now()
            
            duree = (date_fin_estimee - maintenant).total_seconds() / 3600
            
            if duree < 0:
                return 0
            
            return round(duree, 1)
        except Exception:
            return 0


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Sensor for consumption location ID (diagnostic)."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Lieu de Consommation"
        self._attr_unique_id = f"{entry.entry_id}_lieu_conso"
        self._attr_icon = "mdi:identifier"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state."""
        if not self.coordinator.data:
            return None
        
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
            
        return data.get("idLieuConso")
