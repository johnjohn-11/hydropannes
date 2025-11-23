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
        HydroPannesClientsAffectesSensor(coordinator, entry, nom_lieu),
        HydroPannesDebutPanneSensor(coordinator, entry, nom_lieu),
        HydroPannesFinEstimeeSensor(coordinator, entry, nom_lieu),
        HydroPannesStatutInterventionSensor(coordinator, entry, nom_lieu),
        HydroPannesCausePanneSensor(coordinator, entry, nom_lieu),
        HydroPannesDureePanneSensor(coordinator, entry, nom_lieu),
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
            "manufacturer": "Hydro-Québec",
            "model": "Surveillance de pannes",
        }

    def _get_interruption(self):
        """Get first interruption if exists."""
        if self.coordinator.data and "interruptions" in self.coordinator.data:
            interruptions = self.coordinator.data["interruptions"]
            if interruptions and len(interruptions) > 0:
                return interruptions[0]
        return None

    def _get_active_outage(self):
        """Get the first active outage (not planned intervention)."""
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None
        
        interruptions = self.coordinator.data["interruptions"]
        for interruption in interruptions:
            # Skip planned interventions ONLY if they are not finished
            if interruption.get("interruptionPlanifiee") is True:
                # If intervention is finished (has dateFin or etat T), include it
                if not interruption.get("dateFin") and interruption.get("etat") != "T":
                    continue
            # Return first non-planned interruption or finished planned intervention
            return interruption
        
        return None

    def _get_planned_intervention(self):
        """Get the first planned intervention."""
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None
        
        interruptions = self.coordinator.data["interruptions"]
        for interruption in interruptions:
            if interruption.get("interruptionPlanifiee") is True:
                return interruption
        
        return None

    def _is_panne_active(self):
        """Check if there's an active outage."""
        if not self.coordinator.data:
            return False
        
        etat = self.coordinator.data.get("etat")
        if etat != "N":
            return False
        
        # Check if there's an active outage (non-planned)
        outage = self._get_active_outage()
        if not outage:
            return False
        
        # Check if outage is not completed
        return outage.get("etat") != "C" and not outage.get("dateFin")



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
        
        if self.coordinator.data and "date" in self.coordinator.data:
            date_str = self.coordinator.data["date"]
            try:
                date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return date_obj
            except Exception:
                pass
        
        return None


class HydroPannesClientsAffectesSensor(HydroPannesSensorBase):
    """Sensor for affected clients."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Clients Affectés"
        self._attr_unique_id = f"{entry.entry_id}_clients_affectes"
        self._attr_native_unit_of_measurement = "clients"
        self._attr_icon = "mdi:account-multiple"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state."""
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
        if not outage or outage.get("etat") == "C":
            return 0
        
        return outage.get("nbClient", 0)


class HydroPannesDebutPanneSensor(HydroPannesSensorBase):
    """Sensor for outage start time."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Début Panne"
        self._attr_unique_id = f"{entry.entry_id}_debut_panne"
        self._attr_icon = "mdi:clock-start"
        self._attr_device_class = "timestamp"

    @property
    def native_value(self):
        """Return the state as ISO timestamp."""
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
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
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
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
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
        if not outage:
            return "Aucune intervention"
        
        if outage.get("dateFin") or outage.get("etat") == "C":
            return "Aucune intervention"
        
        code = outage.get("codeIntervention")
        if code:
            return INTERVENTION_CODES.get(code, "Inconnu")
        
        return "Aucune intervention"




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
    try:
        _LOGGER.debug("InfoPannes - Starting native_value")
        
        if not self.coordinator.data:
            _LOGGER.warning("InfoPannes - No coordinator data")
            return "Indisponible"
        
        # Gestion des deux formats possibles
        if isinstance(self.coordinator.data, list):
            data = self.coordinator.data[0]
        else:
            data = self.coordinator.data
        
        etat = data.get("etat")
        interruptions = data.get("interruptions", [])
        
        _LOGGER.debug(f"InfoPannes - etat principal: {etat}, nb interruptions: {len(interruptions)}")
        
        # No interruptions
        if not interruptions or len(interruptions) == 0:
            if etat == "A":
                return "Aucune panne détectée"
            else:
                return "Indisponible"
        
        # Check for active outage (non-planned) - PRIORITY 1
        active_outage = None
        for interruption in interruptions:
            if not interruption.get("interruptionPlanifiee", False):
                active_outage = interruption
                _LOGGER.debug(f"InfoPannes - Found active outage with etat: {interruption.get('etat')}")
                break
        
        # Check for planned intervention - PRIORITY 2
        planned = None
        for interruption in interruptions:
            if interruption.get("interruptionPlanifiee", False):
                planned = interruption
                _LOGGER.debug(f"InfoPannes - Found planned intervention with etat: {interruption.get('etat')}")
                break
        
        # Process active outage first (if exists)
        if active_outage:
            outage_etat = active_outage.get("etat")
            
            # Check if outage is ongoing (C = en cours, P = prévu)
            if outage_etat in ["C", "P"]:
                return "Panne en cours"
            
            # Check if outage was restored (T = terminé)
            if outage_etat == "T" or active_outage.get("dateFin"):
                return "Courant rétabli"
        
        # Process planned intervention (if no active outage or after outage processed)
        if planned:
            planned_etat = planned.get("etat")
            
            _LOGGER.debug(f"InfoPannes - Planned etat: {planned_etat}, has dateFin: {planned.get('dateFin') is not None}")
            
            # Intervention planifiée terminée (T = terminé)
            if planned_etat == "T":
                return "Intervention planifiée terminée"
            
            # Also check if has dateFin and etat is A
            if planned.get("dateFin") and etat == "A":
                return "Intervention planifiée terminée"
            
            # Intervention planifiée en cours (C = en cours)
            if planned_etat == "C":
                return "Intervention planifiée en cours"
            
            # Also check if etat is N (panne détectée)
            if etat == "N" and planned_etat in ["C", "P"]:
                return "Intervention planifiée en cours"
            
            # Intervention planifiée à venir (P = prévu)
            if planned_etat == "P" and etat == "A":
                return "Interruption planifiée à venir"
            
            # Check date for future intervention
            if etat == "A" and planned.get("dateDebut") and not planned.get("dateFin"):
                try:
                    date_debut = datetime.fromisoformat(planned["dateDebut"].replace("Z", "+00:00"))
                    maintenant = dt_util.now()
                    
                    if date_debut > maintenant:
                        return "Interruption planifiée à venir"
                except Exception as e:
                    _LOGGER.error(f"InfoPannes - Error parsing date: {e}")
        
        # Default based on etat
        if etat == "A":
            return "Aucune panne détectée"
        
        return "Indisponible"
        
    except Exception as e:
        _LOGGER.error(f"InfoPannes - Error in native_value: {e}", exc_info=True)
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
        try:
            _LOGGER.debug("InfoPannes - Starting extra_state_attributes")
            
            if not self.coordinator.data:
                _LOGGER.warning("InfoPannes - No coordinator data")
                return {}
            
            _LOGGER.debug(f"InfoPannes - Coordinator data type: {type(self.coordinator.data)}")
            
            # Gestion des deux formats possibles
            if isinstance(self.coordinator.data, list):
                _LOGGER.debug("InfoPannes - Data is a list")
                data = self.coordinator.data[0]
            else:
                _LOGGER.debug("InfoPannes - Data is a dict")
                data = self.coordinator.data
            
            _LOGGER.debug(f"InfoPannes - Data keys: {data.keys()}")
            
            interruptions = data.get("interruptions", [])
            _LOGGER.debug(f"InfoPannes - Interruptions count: {len(interruptions)}")
            
            if not interruptions or len(interruptions) == 0:
                _LOGGER.warning("InfoPannes - No interruptions found")
                return {}
            
            # PRIORITY 1: Panne en cours (non planifiée)
            panne_en_cours = None
            for interruption in interruptions:
                if not interruption.get("interruptionPlanifiee", False):
                    panne_en_cours = interruption
                    _LOGGER.debug("InfoPannes - Found panne en cours")
                    break
            
            # PRIORITY 2: Intervention planifiée
            intervention_planifiee = None
            for interruption in interruptions:
                if interruption.get("interruptionPlanifiee", False):
                    intervention_planifiee = interruption
                    _LOGGER.debug("InfoPannes - Found intervention planifiée")
                    break
            
            # Use panne en cours if available, otherwise planned intervention
            active_interruption = panne_en_cours if panne_en_cours else intervention_planifiee
            
            # Fallback to first interruption if neither found
            if active_interruption is None:
                active_interruption = interruptions[0]
                _LOGGER.debug("InfoPannes - Using first interruption as fallback")
            
            _LOGGER.debug(f"InfoPannes - Active interruption keys: {active_interruption.keys()}")
            
            attributes = {
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
            
            _LOGGER.debug(f"InfoPannes - Returning attributes: {attributes}")
            return attributes
            
        except Exception as e:
            _LOGGER.error(f"InfoPannes - Error in extra_state_attributes: {e}", exc_info=True)
            return {}
class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
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
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
        if not outage:
            return "Aucune intervention"
        
        if outage.get("dateFin") or outage.get("etat") == "C":
            return "Aucune intervention"
        
        code = outage.get("codeIntervention")
        if code:
            return INTERVENTION_CODES.get(code, "Inconnu")
        
        return "Aucune intervention"


class HydroPannesCausePanneSensor(HydroPannesSensorBase):
    """Sensor for outage cause."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Cause Panne"
        self._attr_unique_id = f"{entry.entry_id}_cause_panne"
        self._attr_icon = "mdi:help-circle-outline"

    @property
    def native_value(self):
        """Return the state."""
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
        if not outage:
            return "Aucune panne"
        
        if outage.get("etat") == "C":
            return "Aucune panne"
        
        code = str(outage.get("codeCause", ""))
        if code:
            cause_text = CAUSE_CODES.get(code, "Bris d'équipement")
            return f"{cause_text} ({code})"
        
        return "Aucune panne"


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


class HydroPannesDureePanneSensor(HydroPannesSensorBase):
    """Sensor for outage duration."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée Panne"
        self._attr_unique_id = f"{entry.entry_id}_duree_panne"
        self._attr_native_unit_of_measurement = "heures"
        self._attr_icon = "mdi:timer-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state."""
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
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
        # Get active outage (not planned intervention)
        outage = self._get_active_outage()
        
        if not outage:
            return 0
        
        if outage.get("dateFin") or outage.get("etat") == "C":
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
        
        etat = self.coordinator.data.get("etat")
        interruptions = self.coordinator.data.get("interruptions", [])
        
        # No interruptions = no outage detected
        if not interruptions or len(interruptions) == 0:
            return "Aucune panne détectée"
        
        # Check for active outage (non-planned)
        active_outage = self._get_active_outage()
        
        # Priority 1: Active outage
        if active_outage:
            # Check if outage has dateFin in the past (restored)
            if active_outage.get("dateFin"):
                try:
                    date_fin = datetime.fromisoformat(active_outage["dateFin"].replace("Z", "+00:00"))
                    maintenant = dt_util.now()
                    if date_fin < maintenant:
                        return "Courant rétabli"
                except Exception:
                    pass
            
            # Check if etat is "C" (completed)
            if active_outage.get("etat") == "C":
                return "Courant rétabli"
            
            # Otherwise it's ongoing
            return "Panne en cours"
        
        # Priority 2: Planned intervention (only if no active outage)
        planned = self._get_planned_intervention()
        if planned:
            # Check if it's in the future
            if planned.get("dateDebut"):
                try:
                    date_debut = datetime.fromisoformat(planned["dateDebut"].replace("Z", "+00:00"))
                    maintenant = dt_util.now()
                    
                    if date_debut > maintenant:
                        return "Interruption planifiée à venir"
                except Exception:
                    pass
        
        # If etat is "A" and no active outage, everything is fine
        if etat == "A":
            return "Aucune panne détectée"
        
        # Default
        return "Aucune panne détectée"

    @property
    def icon(self):
        """Return the icon."""
        state = self.native_value
        if state == "Aucune panne détectée":
            return "mdi:check-circle"
        elif state == "Courant rétabli":
            return "mdi:check-circle-outline"
        elif state == "Interruption planifiée à venir":
            return "mdi:calendar-clock"
        elif state == "Panne en cours":
            return "mdi:alert-circle"
        return "mdi:help-circle"


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
        
        return self.coordinator.data.get("idLieuConso")
