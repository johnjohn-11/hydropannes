"""Support for Hydro-Pannes sensors."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
            return "Indisponible"

        etat = self.coordinator.data.get("etat")
        interruptions = self.coordinator.data.get("interruptions", [])

        # No interruptions
        if not interruptions:
            if etat == "A":
                return "Aucune panne détectée"
            return "Indisponible"

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
            return "Panne en cours"

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

        return "Indisponible"

    @proper
