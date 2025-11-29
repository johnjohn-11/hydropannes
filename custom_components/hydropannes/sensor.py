"""Support for Hydro-Pannes sensors."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CAUSE_CODES,
    CONF_NOM_LIEU,
    DOMAIN,
    INTERVENTION_CODES,
)
from .coordinator import HydroPannesDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes sensors."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
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


class HydroPannesSensorBase(CoordinatorEntity[HydroPannesDataUpdateCoordinator], SensorEntity):
    """Base class for Hydro-Pannes sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HydroPannes {self._nom_lieu}",
            manufacturer=None,
            model="Info-pannes",
        )

    # ==========================================================================
    # Helper methods
    # ==========================================================================

    def _parse_dt(self, value: str | None) -> datetime | None:
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

    def _is_terminated(self, intr: dict[str, Any]) -> bool:
        """
        Check if an interruption is terminated.

        An interruption is considered terminated if:
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

    def _is_future(self, intr: dict[str, Any]) -> bool:
        """
        Check if an interruption is scheduled for the future.

        Returns True if etat == 'P' (Planned/Future) or dateDebut is in the future.
        """
        if not intr:
            return False
        if intr.get("etat") == "P":
            return True
        date_debut = self._parse_dt(intr.get("dateDebut"))
        if date_debut and date_debut > dt_util.now():
            return True
        return False

    def _get_active_outage(self) -> dict[str, Any] | None:
        """
        Get the first active non-planned outage.

        Priority logic:
        - Must have interruptionPlanifiee = False
        - Must NOT be terminated (no dateFin, etat not in C/T)
        - Must NOT be future (etat != P, dateDebut not in future)

        Returns the first matching interruption or None.
        """
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None

        interruptions = self.coordinator.data["interruptions"]
        for intr in interruptions:
            # Skip planned interventions
            if intr.get("interruptionPlanifiee", False):
                continue
            # Skip terminated interruptions
            if self._is_terminated(intr):
                continue
            # Skip future interruptions
            if self._is_future(intr):
                continue
            return intr
        return None

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """
        Get the most relevant planned intervention.

        Priority logic:
        - Must have interruptionPlanifiee = True
        - Prefer active (not terminated) over terminated
        - If multiple, return the most recent by dateDebut/datePublication

        Returns the most relevant planned intervention or None.
        """
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None

        interruptions = self.coordinator.data["interruptions"]
        planned = [i for i in interruptions if i.get("interruptionPlanifiee", False)]
        if not planned:
            return None

        # Prefer active planned interventions (not terminated)
        for p in planned:
            if not self._is_terminated(p):
                return p

        # Fallback: return the most recent by dateDebut or datePublication
        def _sort_key(i: dict[str, Any]) -> datetime:
            db = self._parse_dt(i.get("dateDebut"))
            if db:
                return db
            dp = self._parse_dt(i.get("datePublication"))
            return dp or datetime.min

        return sorted(planned, key=_sort_key)[-1]

    def _get_terminated_outage(self) -> dict[str, Any] | None:
        """
        Get a terminated non-planned outage (for "Courant rétabli" state).

        Returns the first non-planned interruption that has dateFin set.
        """
        if not self.coordinator.data or "interruptions" not in self.coordinator.data:
            return None

        interruptions = self.coordinator.data["interruptions"]
        for intr in interruptions:
            # Must be non-planned
            if intr.get("interruptionPlanifiee", False):
                continue
            # Must have dateFin (terminated)
            if intr.get("dateFin"):
                return intr
        return None


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """
    Sensor for service status info.

    Logic (in priority order):
    -------------------------
    PRIORITY 1 - Active non-planned outage:
      - If etat = "N" -> "Panne en cours"
      - If etat = "A" or "N" and dateFin exists and interruptionPlanifiee = False
        -> "Courant rétabli"

    PRIORITY 2 - Planned intervention:
      - If etat = "A" or "N" and dateFin exists and interruptionPlanifiee = True
        -> "Intervention planifiée terminée"
      - If etat = "N" and no dateFin and interruptionPlanifiee = True
        -> "Intervention planifiée en cours"
      - If etat = "A" and dateDebut in future
        -> "Interruption planifiée à venir"

    FALLBACK:
      - If etat = "A" and no dateDebut -> "Aucune panne détectée"
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Info-pannes"
        self._attr_unique_id = f"{entry.entry_id}_info_pannes"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self) -> str | None:
        """Return the state based on priority logic."""
        if not self.coordinator.data:
            return None

        etat = self.coordinator.data.get("etat")
        interruptions = self.coordinator.data.get("interruptions", [])

        # No interruptions at all
        if not interruptions:
            if etat == "A":
                return "Aucune panne détectée"
            return None

        # =======================================================================
        # PRIORITY 1: Non-planned outage (active or recently terminated)
        # =======================================================================
        active_outage = self._get_active_outage()
        if active_outage:
            # Active non-planned outage with main etat = "N"
            if etat == "N":
                return "Panne en cours"

        # Check for terminated non-planned outage (Courant rétabli)
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            # etat can be "A" or "N" with dateFin present and interruptionPlanifiee = False
            return "Courant rétabli"

        # =======================================================================
        # PRIORITY 2: Planned intervention
        # =======================================================================
        planned = self._get_planned_intervention()
        if planned:
            # Terminated planned intervention
            if self._is_terminated(planned) or planned.get("dateFin"):
                return "Intervention planifiée terminée"

            # Active planned intervention (etat = "N", no dateFin)
            if etat == "N" and not planned.get("dateFin"):
                return "Intervention planifiée en cours"

            # Future planned intervention (etat = "A", dateDebut in future)
            if etat == "A":
                date_debut = self._parse_dt(planned.get("dateDebut"))
                if date_debut and date_debut > dt_util.now():
                    return "Interruption planifiée à venir"

            # Generic planned state
            return "Interruption planifiée"

        # =======================================================================
        # FALLBACK: No active or planned interruptions
        # =======================================================================
        if etat == "A":
            return "Aucune panne détectée"

        return None

    @property
    def icon(self) -> str:
        """Return the icon based on current state."""
        state = self.native_value
        if state == "Aucune panne détectée":
            return "mdi:check-circle"
        if state in ["Courant rétabli", "Intervention planifiée terminée"]:
            return "mdi:check-circle-outline"
        if state in [
            "Interruption planifiée à venir",
            "Intervention planifiée en cours",
            "Interruption planifiée",
        ]:
            return "mdi:calendar-clock"
        if state == "Panne en cours":
            return "mdi:alert-circle"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Return extra attributes from the active interruption.

        Priority: active outage > planned intervention > first interruption
        """
        if not self.coordinator.data:
            return {}

        interruptions = self.coordinator.data.get("interruptions", [])
        if not interruptions:
            return {}

        # Select interruption based on priority
        inter = self._get_active_outage()
        if not inter:
            inter = self._get_terminated_outage()
        if not inter:
            inter = self._get_planned_intervention()
        if not inter:
            inter = interruptions[0]

        attrs: dict[str, Any] = {}
        for key in [
            "dateDebut",
            "dateFin",
            "etat",
            "dateFinEstimeeMin",
            "dateFinEstimeeMax",
            "codeIntervention",
            "niveauUrgence",
            "nbClient",
            "codeCause",
            "codeMunicipal",
            "datePublication",
            "codeRemarque",
            "dureePrevu",
            "probabilite",
            "interruptionPlanifiee",
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
    """
    Sensor for urgency level.

    Logic:
    ------
    Priority: active outage > planned intervention

    Values:
      - "P" -> "Panne"
      - "N" -> "Panne majeure"
      - Other -> "Inconnu (code)"
      - No interruption -> None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Niveau d'urgence"
        self._attr_unique_id = f"{entry.entry_id}_niveau_urgence"
        self._attr_icon = "mdi:alert-octagon"

    @property
    def native_value(self) -> str | None:
        """Return the urgency level."""
        # Priority 1: active non-planned outage
        interruption = self._get_active_outage()

        # Priority 2: planned intervention
        if not interruption:
            interruption = self._get_planned_intervention()

        if not interruption or "niveauUrgence" not in interruption:
            return None

        niveau = interruption.get("niveauUrgence")

        if niveau == "P":
            return "Panne"
        if niveau == "N":
            return "Panne majeure"
        return f"Inconnu ({niveau})" if niveau else None


class HydroPannesNombreClientSensor(HydroPannesSensorBase):
    """
    Sensor for affected clients/addresses.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Returns: nbClient value or None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Adresses touchées"
        self._attr_unique_id = f"{entry.entry_id}_nbclient"
        self._attr_native_unit_of_measurement = "clients"
        self._attr_icon = "mdi:account-multiple"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the number of affected clients."""
        # Priority 1: active non-planned outage
        outage = self._get_active_outage()

        # Priority 2: planned intervention
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        return outage.get("nbClient")


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """
    Sensor for outage start time.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Returns: dateDebut as ISO 8601 timestamp or None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Date début"
        self._attr_unique_id = f"{entry.entry_id}_date_debut"
        self._attr_icon = "mdi:clock-start"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the outage start time."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage or "dateDebut" not in outage:
            return None

        return self._parse_dt(outage["dateDebut"])


class HydroPannesFinEstimeeSensor(HydroPannesSensorBase):
    """
    Sensor for estimated or actual end time.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Sub-priority for value:
      1. dateFin (actual end)
      2. dateFinEstimeeMax (estimated end)

    Icons:
      - mdi:clock-check (actual end time - dateFin)
      - mdi:clock-alert (estimated end time - dateFinEstimeeMax)

    Returns: datetime or None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Date fin estimée ou réelle"
        self._attr_unique_id = f"{entry.entry_id}_datefin"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _get_end_time_info(self) -> tuple[datetime | None, bool]:
        """
        Get end time and whether it's actual or estimated.

        Returns: (datetime or None, is_actual: bool)
        """
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None, False

        # Sub-priority 1: actual end time (dateFin)
        date_fin = self._parse_dt(outage.get("dateFin"))
        if date_fin:
            return date_fin, True

        # Sub-priority 2: estimated end time (dateFinEstimeeMax)
        date_fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if date_fin_estimee:
            return date_fin_estimee, False

        return None, False

    @property
    def native_value(self) -> datetime | None:
        """Return the actual or estimated end time."""
        end_time, _ = self._get_end_time_info()
        return end_time

    @property
    def icon(self) -> str:
        """Return icon based on whether end time is actual or estimated."""
        end_time, is_actual = self._get_end_time_info()
        if end_time is None:
            return "mdi:clock-end"
        if is_actual:
            return "mdi:clock-check"  # Actual end time (dateFin)
        return "mdi:clock-alert"  # Estimated end time (dateFinEstimeeMax)


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """
    Sensor for intervention status.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Values:
      - If dateFin exists and not in future -> "Intervention terminée"
      - Otherwise -> INTERVENTION_CODES[codeIntervention]
      - No intervention -> None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Statut intervention"
        self._attr_unique_id = f"{entry.entry_id}_statut_intervention"
        self._attr_icon = "mdi:account-hard-hat"

    @property
    def native_value(self) -> str | None:
        """Return the intervention status."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        # Check if intervention is terminated
        date_fin = self._parse_dt(outage.get("dateFin"))
        if date_fin and date_fin <= dt_util.now():
            return "Intervention terminée"

        # Return intervention code text
        code = outage.get("codeIntervention")
        if code:
            return INTERVENTION_CODES.get(code)

        return None


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """
    Sensor for outage cause.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Returns: "Cause text (code)" or None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Cause"
        self._attr_unique_id = f"{entry.entry_id}_cause"
        self._attr_icon = "mdi:help-circle-outline"

    @property
    def native_value(self) -> str | None:
        """Return the outage cause."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        code = outage.get("codeCause")
        if code is None:
            return None

        code_str = str(code)
        cause_text = CAUSE_CODES.get(code_str)
        if cause_text:
            return f"{cause_text} ({code_str})"
        return f"Inconnu ({code_str})"


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """
    Sensor for outage duration.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Calculation:
      - If dateFin exists -> (dateFin - dateDebut)
      - Otherwise -> (now - dateDebut)

    Returns: duration in seconds (for Home Assistant unit conversion)
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée"
        self._attr_unique_id = f"{entry.entry_id}_duree"
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_icon = "mdi:timer-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the duration in seconds."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage or "dateDebut" not in outage:
            return None

        try:
            date_debut = self._parse_dt(outage["dateDebut"])
            if not date_debut:
                return None

            # If dateFin exists, calculate actual duration
            if outage.get("dateFin"):
                date_fin = self._parse_dt(outage["dateFin"])
                if not date_fin:
                    return None
                duration_seconds = (date_fin - date_debut).total_seconds()
            else:
                # Calculate ongoing duration
                duration_seconds = (dt_util.now() - date_debut).total_seconds()

            return round(duration_seconds)
        except Exception:
            _LOGGER.exception("Error calculating duration")
            return None


class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """
    Sensor for time until power restoration.

    Logic:
    ------
    Priority 1: active non-planned outage
    Priority 2: planned intervention

    Calculation:
      - If dateFin exists -> None (already terminated)
      - If dateFinEstimeeMax exists -> (dateFinEstimeeMax - now)
      - If result is negative -> None

    Returns: duration in seconds (for Home Assistant unit conversion)
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Durée avant rétablissement"
        self._attr_unique_id = f"{entry.entry_id}_duree_avant_retablissement"
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_icon = "mdi:timer-sand"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the time until restoration in seconds."""
        outage = self._get_active_outage()
        if not outage:
            outage = self._get_planned_intervention()

        if not outage:
            return None

        # If already terminated, return None
        if outage.get("dateFin") or outage.get("etat") == "T":
            return None

        date_fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if not date_fin_estimee:
            return None

        duration_seconds = (date_fin_estimee - dt_util.now()).total_seconds()
        if duration_seconds < 0:
            return None

        return round(duration_seconds)


class HydroPannesDerniereMAJSensor(HydroPannesSensorBase):
    """
    Sensor for last update time.

    Logic:
    ------
    Priority 1: datePublication from interruption
    Priority 2: date from main level

    Returns: datetime or None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Dernière MAJ"
        self._attr_unique_id = f"{entry.entry_id}_derniere_maj"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the last update time."""
        # Priority 1: datePublication from active interruption
        interruption = self._get_active_outage() or self._get_planned_intervention()
        if interruption and interruption.get("datePublication"):
            parsed = self._parse_dt(interruption.get("datePublication"))
            if parsed:
                return parsed

        # Priority 2: date from main level
        if self.coordinator.data and "date" in self.coordinator.data:
            parsed = self._parse_dt(self.coordinator.data.get("date"))
            if parsed:
                return parsed

        return None


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """
    Sensor for consumption location ID (diagnostic).

    Logic:
    ------
    Returns: idLieuConso from main level or None
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Lieu de consommation"
        self._attr_unique_id = f"{entry.entry_id}_idlieuconso"
        self._attr_icon = "mdi:identifier"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the consumption location ID."""
        if not self.coordinator.data:
            return None

        return self.coordinator.data.get("idLieuConso")
