"""Support for Hydro-Pannes sensors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CAUSE_CODES,
    CONF_NOM_LIEU,
    DOMAIN,
    INTERVENTION_CODES,
)
from .coordinator import HydroPannesDataUpdateCoordinator

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
        HydroPannesEtatAPIBrutSensor(coordinator, entry, nom_lieu),
        HydroPannesEtatInterruptionSensor(coordinator, entry, nom_lieu),
        HydroPannesCodeInterventionSensor(coordinator, entry, nom_lieu),
    ]

    async_add_entities(sensors)


class HydroPannesSensorBase(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator], SensorEntity
):
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
        except (ValueError, TypeError):
            return None

    def _is_date_in_past(self, date_value: datetime | None) -> bool:
        """Check if a datetime is in the past."""
        if not date_value:
            return False
        return date_value <= dt_util.now()

    def _is_date_in_future(self, date_value: datetime | None) -> bool:
        """Check if a datetime is in the future."""
        if not date_value:
            return False
        return date_value > dt_util.now()

    def _get_main_etat(self) -> str | None:
        """Get the main 'etat' field from API response."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("etat")

    def _get_interruptions(self) -> list[dict[str, Any]]:
        """Get the list of interruptions from API response."""
        if not self.coordinator.data:
            return []
        result: list[dict[str, Any]] = self.coordinator.data.get("interruptions", [])
        return result

    def _is_outage_active(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption represents an active outage.

        An outage is considered ACTIVE if:
        - Main etat = "N" (outage state)
        - AND (no dateFin OR dateFin is in the future)

        Note: We ignore the interruption's own 'etat' field (T, C, etc.)
        as it doesn't reliably indicate active state.
        """
        main_etat = self._get_main_etat()
        if main_etat != "N":
            return False

        date_fin = self._parse_dt(intr.get("dateFin"))
        return not date_fin or self._is_date_in_future(date_fin)

    def _is_outage_terminated(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is terminated (power restored).

        An outage is TERMINATED if:
        - dateFin exists AND is in the past
        """
        date_fin = self._parse_dt(intr.get("dateFin"))
        return self._is_date_in_past(date_fin)

    def _is_planned_intervention(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is a planned intervention."""
        result: bool = intr.get("interruptionPlanifiee", False)
        return result

    def _is_future_planned(self, intr: dict[str, Any]) -> bool:
        """Check if an interruption is a future planned intervention.

        Returns True if:
        - interruptionPlanifiee = True
        - AND dateDebut is in the future
        """
        if not self._is_planned_intervention(intr):
            return False

        date_debut = self._parse_dt(intr.get("dateDebut"))
        return self._is_date_in_future(date_debut)

    def _get_active_outage(self) -> dict[str, Any] | None:
        """Get the first active non-planned outage.

        Returns the first interruption where:
        - interruptionPlanifiee = False
        - Main etat = "N"
        - No dateFin or dateFin in the future
        """
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr):
                continue
            if self._is_outage_active(intr):
                return intr
        return None

    def _get_terminated_outage(self) -> dict[str, Any] | None:
        """Get a terminated non-planned outage (for "Courant rétabli" state).

        Returns the first non-planned interruption that has dateFin in the past.
        """
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr):
                continue
            if self._is_outage_terminated(intr):
                return intr
        return None

    def _get_planned_intervention(self) -> dict[str, Any] | None:
        """Get the most relevant planned intervention.

        Priority:
        1. Active planned (main etat = "N", no dateFin or dateFin in future)
        2. Future planned (dateDebut in future)
        3. Any planned intervention
        """
        interruptions = self._get_interruptions()
        planned = [i for i in interruptions if self._is_planned_intervention(i)]
        if not planned:
            return None

        # Priority 1: Active planned intervention
        for p in planned:
            if self._is_outage_active(p):
                return p

        # Priority 2: Future planned intervention
        for p in planned:
            if self._is_future_planned(p):
                return p

        # Priority 3: Any planned (including terminated)
        return planned[0]

    def _get_current_interruption(self) -> dict[str, Any] | None:
        """Get the most relevant interruption for displaying data.

        Priority logic:
        1. Active non-planned outage (ongoing)
        2. Terminated non-planned outage (recently finished - "Courant rétabli")
        3. Planned intervention (active, future, or terminated)
        4. First interruption in list (fallback)

        This method is used by sensors that need to display data even after
        an outage has ended.
        """
        # Priority 1: Active non-planned outage
        interruption = self._get_active_outage()
        if interruption:
            return interruption

        # Priority 2: Terminated non-planned outage
        interruption = self._get_terminated_outage()
        if interruption:
            return interruption

        # Priority 3: Planned intervention
        interruption = self._get_planned_intervention()
        if interruption:
            return interruption

        # Priority 4: Fallback to first interruption if any
        interruptions = self._get_interruptions()
        if interruptions:
            return interruptions[0]

        return None


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """Sensor for service status info.

    Logic (in priority order):
    -------------------------
    PRIORITY 1 - Active non-planned outage:
      - Main etat = "N" AND (no dateFin OR dateFin in future)
      - interruptionPlanifiee = False
      -> "Panne en cours"

    PRIORITY 2 - Terminated non-planned outage:
      - dateFin exists AND is in the past
      - interruptionPlanifiee = False
      -> "Courant rétabli"

    PRIORITY 3 - Planned intervention:
      - interruptionPlanifiee = True
      - If dateFin in past -> "Intervention planifiée terminée"
      - If main etat = "N" -> "Intervention planifiée en cours"
      - If dateDebut in future -> "Interruption planifiée à venir"
      -> "Interruption planifiée" (generic)

    FALLBACK:
      - Main etat = "A" and no relevant interruption -> "Aucune panne détectée"
      - Otherwise -> None
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

        main_etat = self._get_main_etat()
        interruptions = self._get_interruptions()

        # No interruptions at all
        if not interruptions:
            if main_etat == "A":
                return "Aucune panne détectée"
            # Main etat is "N" but no interruptions - unusual state
            if main_etat == "N":
                return "Panne en cours"
            return None

        # PRIORITY 1: Active non-planned outage
        active_outage = self._get_active_outage()
        if active_outage:
            return "Panne en cours"

        # PRIORITY 2: Terminated non-planned outage (Courant rétabli)
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            return "Courant rétabli"

        # PRIORITY 3: Planned intervention
        planned = self._get_planned_intervention()
        if planned:
            # Terminated planned intervention
            if self._is_outage_terminated(planned):
                return "Intervention planifiée terminée"

            # Active planned intervention (main etat = "N")
            if main_etat == "N":
                return "Intervention planifiée en cours"

            # Future planned intervention
            if self._is_future_planned(planned):
                return "Interruption planifiée à venir"

            # Generic planned state
            return "Interruption planifiée"

        # FALLBACK: No active or planned interruptions
        if main_etat == "A":
            return "Aucune panne détectée"

        # Main etat is "N" but couldn't match any interruption state
        if main_etat == "N":
            return "Panne en cours"

        return None

    @property
    def icon(self) -> str:
        """Return the icon based on current state."""
        state = self.native_value
        if state == "Aucune panne détectée":
            return "mdi:check-circle"
        if state in ("Courant rétabli", "Intervention planifiée terminée"):
            return "mdi:check-circle-outline"
        if state in (
            "Interruption planifiée à venir",
            "Intervention planifiée en cours",
            "Interruption planifiée",
        ):
            return "mdi:calendar-clock"
        if state == "Panne en cours":
            return "mdi:alert-circle"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes from the active interruption."""
        if not self.coordinator.data:
            return {}

        interruptions = self._get_interruptions()
        if not interruptions:
            return {"attribution": "Données fournies par Hydro-Québec"}

        # Select interruption based on priority
        inter = self._get_active_outage()
        if not inter:
            inter = self._get_terminated_outage()
        if not inter:
            inter = self._get_planned_intervention()
        if not inter:
            inter = interruptions[0]

        attrs: dict[str, Any] = {}
        for key in (
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
        ):
            val = inter.get(key)
            if key.startswith("date") and val:
                parsed = self._parse_dt(val)
                attrs[key] = parsed.isoformat() if parsed else val
            elif val is not None:
                attrs[key] = val
        attrs["attribution"] = "Données fournies par Hydro-Québec"
        return attrs


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor for urgency level.

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
        self._attr_name = "Niveau urgence"
        self._attr_unique_id = f"{entry.entry_id}_niveau_urgence"
        self._attr_icon = "mdi:alert-octagon"

    @property
    def native_value(self) -> str | None:
        """Return the urgency level."""
        interruption = self._get_current_interruption()

        if not interruption or "niveauUrgence" not in interruption:
            return None

        niveau = interruption.get("niveauUrgence")

        if niveau == "P":
            return "Panne"
        if niveau == "N":
            return "Panne majeure"
        return f"Inconnu ({niveau})" if niveau else None


class HydroPannesNombreClientSensor(HydroPannesSensorBase):
    """Sensor for affected clients/addresses."""

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
        outage = self._get_current_interruption()

        if not outage:
            return None

        nb_client: int | None = outage.get("nbClient")
        return nb_client


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor for outage start time."""

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
        outage = self._get_current_interruption()

        if not outage or "dateDebut" not in outage:
            return None

        return self._parse_dt(outage["dateDebut"])


class HydroPannesFinEstimeeSensor(HydroPannesSensorBase):
    """Sensor for estimated or actual end time.

    Sub-priority for value:
      1. dateFin (actual end)
      2. dateFinEstimeeMax (estimated end)

    Icons:
      - mdi:clock-check (actual end time - dateFin)
      - mdi:clock-alert (estimated end time - dateFinEstimeeMax)
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Date fin"
        self._attr_unique_id = f"{entry.entry_id}_datefin"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _get_end_time_info(self) -> tuple[datetime | None, bool]:
        """Get end time and whether it's actual or estimated.

        Returns: (datetime or None, is_actual: bool)
        """
        outage = self._get_current_interruption()

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
            return "mdi:clock-check"
        return "mdi:clock-alert"


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """Sensor for intervention status.

    Values:
      - If dateFin exists and in the past -> "Intervention terminée"
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
        outage = self._get_current_interruption()

        if not outage:
            return None

        # Check if intervention is terminated (dateFin in the past)
        if self._is_outage_terminated(outage):
            return "Intervention terminée"

        # Return intervention code text
        code = outage.get("codeIntervention")
        if code:
            return INTERVENTION_CODES.get(code)

        return None


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """Sensor for outage cause."""

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
        outage = self._get_current_interruption()

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
    """Sensor for outage duration.

    Calculation:
      - If dateFin exists -> (dateFin - dateDebut)
      - Otherwise -> (now - dateDebut)

    Returns: duration in seconds
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
        outage = self._get_current_interruption()

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
        except (ValueError, TypeError):
            _LOGGER.exception("Error calculating duration")
            return None


class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor for time until power restoration.

    Only shows value for ACTIVE outages.

    Calculation:
      - If outage is terminated (dateFin in past) -> None
      - If dateFinEstimeeMax exists -> (dateFinEstimeeMax - now)
      - If result is negative -> None

    Returns: duration in seconds
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
        # Only consider active outages for this sensor
        outage = self._get_active_outage()
        if not outage:
            # Also check for active planned intervention
            planned = self._get_planned_intervention()
            if planned and self._is_outage_active(planned):
                outage = planned

        if not outage:
            return None

        # If already terminated, return None
        if self._is_outage_terminated(outage):
            return None

        date_fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if not date_fin_estimee:
            return None

        duration_seconds = (date_fin_estimee - dt_util.now()).total_seconds()
        if duration_seconds < 0:
            return None

        return round(duration_seconds)


class HydroPannesDerniereMAJSensor(HydroPannesSensorBase):
    """Sensor for last update time."""

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
        # Priority 1: datePublication from current interruption
        interruption = self._get_current_interruption()
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
    """Sensor for consumption location ID (diagnostic)."""

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Lieu consommation"
        self._attr_unique_id = f"{entry.entry_id}_idlieuconso"
        self._attr_icon = "mdi:identifier"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the consumption location ID."""
        if not self.coordinator.data:
            return None

        lieu: str | None = self.coordinator.data.get("idLieuConso")
        return lieu


class HydroPannesEtatAPIBrutSensor(HydroPannesSensorBase):
    """Diagnostic sensor exposing raw API state for debugging.

    This sensor helps troubleshoot issues by showing:
    - Main 'etat' value from API
    - Number of interruptions
    - Key fields from the first/active interruption

    The state shows the main 'etat' field, attributes contain details.
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "État API brut"
        self._attr_unique_id = f"{entry.entry_id}_etat_api_brut"
        self._attr_icon = "mdi:api"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the main etat from API or None if no data."""
        if not self.coordinator.data:
            return None

        return self._get_main_etat()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return raw API data for debugging."""
        if not self.coordinator.data:
            return {"api_data": None}

        attrs: dict[str, Any] = {
            "etat_principal": self._get_main_etat(),
            "nombre_interruptions": len(self._get_interruptions()),
            "coordinator_last_update_success": self.coordinator.last_update_success,
        }

        # Add coordinator timing info if available (HA 2023.9+)
        if (
            hasattr(self.coordinator, "last_update_success_time")
            and self.coordinator.last_update_success_time
        ):
            attrs["derniere_maj_reussie"] = (
                self.coordinator.last_update_success_time.isoformat()
            )

        # Add raw data from first/active interruption
        interruption = self._get_current_interruption()
        if interruption:
            attrs["interruption_selectionnee"] = {
                "etat": interruption.get("etat"),
                "dateDebut": interruption.get("dateDebut"),
                "dateFin": interruption.get("dateFin"),
                "dateFinEstimeeMax": interruption.get("dateFinEstimeeMax"),
                "interruptionPlanifiee": interruption.get("interruptionPlanifiee"),
                "codeIntervention": interruption.get("codeIntervention"),
                "niveauUrgence": interruption.get("niveauUrgence"),
                "nbClient": interruption.get("nbClient"),
                "codeCause": interruption.get("codeCause"),
            }

        # Add detection flags for debugging
        attrs["detection"] = {
            "active_outage_found": self._get_active_outage() is not None,
            "terminated_outage_found": self._get_terminated_outage() is not None,
            "planned_intervention_found": self._get_planned_intervention() is not None,
        }

        # Add all interruptions summary
        interruptions = self._get_interruptions()
        if interruptions:
            attrs["toutes_interruptions"] = [
                {
                    "index": i,
                    "etat": intr.get("etat"),
                    "dateFin": intr.get("dateFin"),
                    "interruptionPlanifiee": intr.get("interruptionPlanifiee"),
                }
                for i, intr in enumerate(interruptions)
            ]

        return attrs


class HydroPannesEtatInterruptionSensor(HydroPannesSensorBase):
    """Diagnostic sensor for the raw interruption 'etat' field.

    This sensor exposes the 'etat' field from the current interruption
    to help debug API behavior. Common values:
    - "T" : Terminé (Terminated)
    - "C" : Complété (Completed)
    - "A" : Actif (Active)
    - "P" : Planifié (Planned/Future)
    - "R" : En route
    - "L" : Au travail

    Returns None if no interruption exists.
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "État interruption"
        self._attr_unique_id = f"{entry.entry_id}_etat_interruption"
        self._attr_icon = "mdi:state-machine"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the interruption etat field or None if no interruption."""
        interruption = self._get_current_interruption()

        if not interruption:
            return None

        etat: str | None = interruption.get("etat")
        return etat

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional context about the interruption state."""
        interruption = self._get_current_interruption()

        if not interruption:
            return {}

        # Parse dates for display
        date_debut = self._parse_dt(interruption.get("dateDebut"))
        date_fin = self._parse_dt(interruption.get("dateFin"))
        date_fin_estimee = self._parse_dt(interruption.get("dateFinEstimeeMax"))

        attrs: dict[str, Any] = {
            "etat_brut": interruption.get("etat"),
            "etat_principal": self._get_main_etat(),
            "date_debut": date_debut.isoformat() if date_debut else None,
            "date_fin": date_fin.isoformat() if date_fin else None,
            "date_fin_estimee_max": (
                date_fin_estimee.isoformat() if date_fin_estimee else None
            ),
            "interruption_planifiee": interruption.get("interruptionPlanifiee"),
            "code_intervention": interruption.get("codeIntervention"),
        }

        # Add computed status
        attrs["analyse"] = {
            "est_active": self._is_outage_active(interruption),
            "est_terminee": self._is_outage_terminated(interruption),
            "est_planifiee": self._is_planned_intervention(interruption),
            "date_fin_dans_passe": self._is_date_in_past(date_fin),
            "date_fin_dans_futur": self._is_date_in_future(date_fin),
        }

        return attrs


class HydroPannesCodeInterventionSensor(HydroPannesSensorBase):
    """Diagnostic sensor for the raw intervention code.

    This sensor exposes the 'codeIntervention' field from the current
    interruption to help debug API behavior. Common values:
    - "A" : Travaux assignés
    - "L" : Équipe au travail
    - "R" : Équipe en route

    Returns None if no interruption exists.
    """

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Code intervention"
        self._attr_unique_id = f"{entry.entry_id}_code_intervention"
        self._attr_icon = "mdi:wrench"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the intervention code or None if no interruption."""
        interruption = self._get_current_interruption()

        if not interruption:
            return None

        code: str | None = interruption.get("codeIntervention")
        return code

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional context about the intervention code."""
        interruption = self._get_current_interruption()

        if not interruption:
            return {}

        code = interruption.get("codeIntervention")

        return {
            "code_brut": code,
            "description": INTERVENTION_CODES.get(code) if code else None,
            "etat_principal": self._get_main_etat(),
            "etat_interruption": interruption.get("etat"),
            "interruption_planifiee": interruption.get("interruptionPlanifiee"),
        }
