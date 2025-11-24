"""Support for Hydro-Pannes sensors."""
from __future__ import annotations
from datetime import datetime
import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
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
        HydroPannesNombreClientSensor(coordinator, entry, nom_lieu),
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
            "model": "Info-pannes",
        }

    # Helpers (garde le style existant mais corrigé)

    def _parse_dt(self, value: Optional[str]) -> Optional[datetime]:
        """Parse an ISO datetime string to localized datetime or return None."""
        if not value:
            return None
        try:
            dt = dt_util.parse_datetime(value)
            if not dt:
                return None
            return dt_util.as_local(dt)
        except Exception:
            return None

    def _is_terminated(self, intr: Dict[str, Any]) -> bool:
        """Determines if an interruption is terminated."""
        if not intr:
            return False
        # dateFin présent -> terminé (fiable)
        if intr.get("dateFin"):
            return True
        # parfois HQ utilise 'etat' == 'C' ou 'T' pour indiquer complété/terminé
        if intr.get("etat") in ("C", "T"):
            return True
        return False

    def _is_prevue(self, intr: Dict[str, Any]) -> bool:
        """Interruption prévue (future) détectée via etat == 'P'."""
        if not intr:
            return False
        return intr.get("etat") == "P"

    def _get_active_outage(self) -> Optional[Dict[str, Any]]:
        """Get the first active outage (not planned and not terminated)."""
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None

        interruptions = self.coordinator.data["interruptions"]
        for interruption in interruptions:
            # skip if declared planned
            if interruption.get("interruptionPlanifiee", False):
                continue
            # skip if terminated
            if self._is_terminated(interruption):
                continue
            # skip if explicitly marked planned state P (defensive)
            if self._is_prevue(interruption):
                continue
            return interruption
        return None

    def _get_planned_intervention(self) -> Optional[Dict[str, Any]]:
        """Get the first planned intervention.

        Logic:
         - prefer planned interventions that are active (no dateFin and not terminated)
         - otherwise return the most relevant planned (based on dateDebut/datePublication)
        """
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None

        interruptions = self.coordinator.data["interruptions"]
        planned = [i for i in interruptions if i.get("interruptionPlanifiee", False)]
        if not planned:
            return None

        # prefer active planned (no dateFin and not terminated)
        for p in planned:
            if not self._is_terminated(p):
                return p

        # fallback: return the most recent by dateDebut or datePublication
        def _key(i: Dict[str, Any]):
            db = self._parse_dt(i.get("dateDebut"))
            if db:
                return db
            dp = self._parse_dt(i.get("datePublication"))
            return dp or datetime.min

        return sorted(planned, key=_key)[-1]


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """Sensor for service status info."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Info-pannes"
        self._attr_unique_id = f"{entry.entry_id}_info_pannes"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self):
        """Return the state."""
        if not self.coordinator.data:
            return None

        etat = self.coordinator.data.get("etat")
        interruptions = self.coordinator.data.get("interruptions", [])

        # No interruptions
        if not interruptions:
            if etat == "A":
                return "Aucune panne détectée"
            return None

        # PRIORITÉ 1: Panne en cours (non planifiée active)
        active_outage = self._get_active_outage()
        if active_outage:
            # If main etat says N, we have a real outage
            if etat == "N":
                return "Panne en cours"
            # If main etat == A but interruption ended -> courant rétabli (defensive)
            if etat == "A" and self._is_terminated(active_outage):
                return "Courant rétabli"
            # If etat ambiguous, prefer Panne en cours if not terminated
            return None

        # PRIORITÉ 2: Intervention planifiée
        planned = self._get_planned_intervention()
        if planned:
            if self._is_terminated(planned) and etat == "A":
                return "Intervention planifiée terminée"
            if (not self._is_terminated(planned)) and etat == "N":
                # If etat main says N but planned exists and not terminated -> in progress
                return "Intervention planifiée en cours"
            # If planned is future (etat == 'P' or dateDebut in future)
            if planned.get("etat") == "P":
                db = self._parse_dt(planned.get("dateDebut"))
                if db and db > dt_util.now():
                    return "Interruption planifiée à venir"
                return "Interruption planifiée"
            # fallback
            return "Interruption planifiée"

        # fallback: no active outage nor planned intervention
        if etat == "A":
            return "Aucune panne détectée"

        return None

    @property
    def icon(self):
        """Return the icon."""
        state = self.native_value
        if state == "Aucune panne détectée":
            return "mdi:check-circle"
        elif state in ["Courant rétabli", "Intervention planifiée terminée"]:
            return "mdi:check-circle-outline"
        elif state in ["Interruption planifiée à venir", "Intervention planifiée en cours", "Interruption planifiée"]:
            return "mdi:calendar-clock"
        elif state == "Panne en cours":
            return "mdi:alert-circle"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return {}

        # Priority for attributes: 1) active non-planned outage 2) planned intervention 3) most recent interruption
        inter = self._get_active_outage()
        if not inter:
            inter = self._get_planned_intervention()
        if not inter:
            inter = interruptions[0]

        attrs = {}
        for key in [
            "dateDebut", "dateFin", "etat", "dateFinEstimeeMin", "dateFinEstimeeMax",
            "codeIntervention", "niveauUrgence", "nbClient", "codeCause", "codeMunicipal",
            "datePublication", "codeRemarque", "dureePrevu", "probabilite", "interruptionPlanifiee",
        ]:
            val = inter.get(key)
            if key.startswith("date") and val:
                parsed = self._parse_dt(val)
                attrs[key] = parsed.isoformat() if parsed else val
            elif val is not None:
                attrs[key] = val
        attrs["attribution"] = "Données fournies par Hydro-Québec"
        return attrs


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor for urgency level."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Niveau d'urgence"
        self._attr_unique_id = f"{entry.entry_id}_niveau_urgence"
        self._attr_icon = "mdi:alert-octagon"

    @property
    def native_value(self):
        """Return the state."""
        # Priorité à la panne en cours
        interruption = self._get_active_outage()

        # Si pas de panne en cours, prendre l'intervention planifiée
        if not interruption:
            interruption = self._get_planned_intervention()

        if not interruption or "niveauUrgence" not in interruption:
            return None

        niveau = interruption.get("niveauUrgence")

        if niveau == "P":
            return "Panne"
        elif niveau == "N":
            return "Panne majeure"
        else:
            return f"Inconnu ({niveau})" if niveau else None


class HydroPannesNombreClientSensor(HydroPannesSensorBase):
    """Sensor for affected clients."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Adresses touchées"
        self._attr_unique_id = f"{entry.entry_id}_nbclients"
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
            return None

        return outage.get("nbClient", None)


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
        """Return the state as localized datetime."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage or "dateDebut" not in outage:
            return None

        return self._parse_dt(outage["dateDebut"])


class HydroPannesFinEstimeeSensor(HydroPannesSensorBase):
    """Sensor for estimated end time."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Fin réelle ou estimée"
        self._attr_unique_id = f"{entry.entry_id}_fin"
        self._attr_icon = "mdi:clock-end"
        self._attr_device_class = "timestamp"

    @property
    def native_value(self):
        """Return the state as localized datetime."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        # Priority 1: dateFin (real)
        df = self._parse_dt(outage.get("dateFin"))
        if df:
            return df

        # Priority 2: dateFinEstimeeMax
        df2 = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if df2:
            return df2

        return None


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """Sensor for intervention status."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Statut intervention"
        self._attr_unique_id = f"{entry.entry_id}_statut_intervention"
        self._attr_icon = "mdi:account-hard-hat"

    @property
    def native_value(self):
        """Return the state."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        if outage.get("dateFin") or outage.get("etat") == "T":
            return "Intervention terminée"

        code = outage.get("codeIntervention")
        if code:
            return INTERVENTION_CODES.get(code, None)

        return "Aucune intervention"


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
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        code = outage.get("codeCause")
        if code is None:
            return None
        code_str = str(code)
        cause_text = CAUSE_CODES.get(code_str, None)
        return f"{cause_text} ({code_str})"


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor for outage duration."""
    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée"
        self._attr_unique_id = f"{entry.entry_id}_duree"
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_icon = "mdi:timer-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT
    
    @property
    def native_value(self):
        """Return the state (seconds)."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage or "dateDebut" not in outage:
            return None
        
        try:
            date_debut = self._parse_dt(outage["dateDebut"])
            if not date_debut:
                return None
            
            if outage.get("dateFin"):
                date_fin = self._parse_dt(outage["dateFin"])
                if not date_fin:
                    return None
                duree_seconds = (date_fin - date_debut).total_seconds()
            else:
                maintenant = dt_util.now()
                duree_seconds = (maintenant - date_debut).total_seconds()
            
            return round(duree_seconds)
        except Exception:
            return None

class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor for time until power restoration."""
    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée avant rétablissement"
        self._attr_unique_id = f"{entry.entry_id}_duree_avant_retablissement"
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_icon = "mdi:timer-sand"
        self._attr_state_class = SensorStateClass.MEASUREMENT
    
    @property
    def native_value(self):
        """Return the state (seconds) until estimated end."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()
        
        if not outage:
            return None
        
        if outage.get("dateFin") or outage.get("etat") == "T":
            return None
        
        dfm = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if not dfm:
            return None
        
        duree_seconds = (dfm - dt_util.now()).total_seconds()
        if duree_seconds < 0:
            return None
        
        return round(duree_seconds)

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
        """Return the state as localized datetime."""
        interruption = self._get_active_outage() or self._get_planned_intervention()
        if interruption and interruption.get("datePublication"):
            parsed = self._parse_dt(interruption.get("datePublication"))
            if parsed:
                return parsed

        if self.coordinator.data and "date" in self.coordinator.data:
            parsed = self._parse_dt(self.coordinator.data.get("date"))
            if parsed:
                return parsed

        return None


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Sensor for consumption location ID (diagnostic)."""

    def __init__(self, coordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Lieu de consommation"
        self._attr_unique_id = f"{entry.entry_id}_lieu_conso"
        self._attr_icon = "mdi:identifier"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state."""
        if not self.coordinator.data:
            return None

        return self.coordinator.data.get("idLieuConso")
