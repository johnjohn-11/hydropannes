"""Support for Hydro-Pannes sensors."""

from __future__ import annotations

from datetime import datetime
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
    ATTRIBUTION,
    CAUSE_CODES,
    DOMAIN,
    INFO_PANNES_STATES,
    INTERVENTION_CODES,
    INTERVENTION_CODES_MAJEUR,
    NIVEAU_URGENCE_CODES,
    TYPE_FIN_PREVUE_CODES,
)
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes sensors for a config entry."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.title

    async_add_entities([
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
    ])


class HydroPannesSensorBase(
    HydroPannesHelperMixin,
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    SensorEntity,
):
    """Base class for all Hydro-Pannes sensors."""

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
    def available(self) -> bool:
        """Return True only when the coordinator has successfully fetched data."""
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HydroPannes {self._nom_lieu}",
            manufacturer="Hydro-Québec",
            model="Info-pannes",
        )


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """Sensor reporting the overall service status."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Info-pannes"
        self._attr_unique_id = f"{entry.entry_id}_info_pannes"
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self) -> str | None:
        """Return the service status string."""
        if not self.coordinator.data:
            return None

        main_etat = self._get_main_etat()
        interruptions = self._get_interruptions()

        if not interruptions:
            if main_etat == "A":
                return INFO_PANNES_STATES["aucune_panne"]
            if main_etat == "N":
                return INFO_PANNES_STATES["panne_en_cours"]
            return None

        active_outage = self._get_active_outage()
        if active_outage and self.coordinator.data.get("repriseGraduellePossible"):
            return INFO_PANNES_STATES["reprise_graduelle"]

        if active_outage:
            if active_outage.get("niveauUrgence") == "P":
                return INFO_PANNES_STATES["panne_majeure"]
            return INFO_PANNES_STATES["panne_en_cours"]

        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            planned_check = self._get_planned_intervention()
            if (
                not planned_check
                or self._is_aip_annulee(planned_check)
                or self._is_outage_terminated(planned_check)
            ):
                return INFO_PANNES_STATES["service_retabli"]

        planned = self._get_planned_intervention()
        if planned:
            if self._is_aip_annulee(planned):
                return INFO_PANNES_STATES["aip_annulee"]
            if self._is_outage_terminated(planned):
                return INFO_PANNES_STATES["aip_terminee"]
            if main_etat == "N":
                return INFO_PANNES_STATES["aip_en_cours"]
            return INFO_PANNES_STATES["aip_a_venir"]

        if main_etat == "A":
            return INFO_PANNES_STATES["aucune_panne"]
        if main_etat == "N":
            return INFO_PANNES_STATES["panne_en_cours"]
        return None

    @property
    def icon(self) -> str:
        """Return an icon matching the current service status."""
        state = self.native_value
        if state == INFO_PANNES_STATES["aucune_panne"]:
            return "mdi:check-circle"
        if state in (INFO_PANNES_STATES["service_retabli"], INFO_PANNES_STATES["aip_terminee"]):
            return "mdi:check-circle-outline"
        if state in (INFO_PANNES_STATES["aip_a_venir"], INFO_PANNES_STATES["aip_en_cours"], INFO_PANNES_STATES["aip_annulee"]):
            return "mdi:calendar-clock"
        if state == INFO_PANNES_STATES["panne_majeure"]:
            return "mdi:alert-octagon"
        if state == INFO_PANNES_STATES["reprise_graduelle"]:
            return "mdi:restore-alert"
        if state == INFO_PANNES_STATES["panne_en_cours"]:
            return "mdi:alert-circle"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the selected interruption."""
        if not self.coordinator.data:
            return {}
        interruptions = self._get_interruptions()
        if not interruptions:
            return {"attribution": ATTRIBUTION}
        inter = self._get_current_interruption()
        if not inter:
            return {"attribution": ATTRIBUTION}
        attrs: dict[str, Any] = {}
        for key in (
            "dateDebut", "dateFin", "etat", "dateFinEstimeeMin", "dateFinEstimeeMax",
            "dateDebutReport", "dateFinReport", "codeIntervention", "niveauUrgence",
            "nbClient", "codeCause", "codeMunicipal", "datePublication", "codeRemarque",
            "dureePrevu", "probabilite", "interruptionPlanifiee", "typeFinPrevue",
        ):
            val = inter.get(key)
            if key.startswith("date") and val:
                parsed = self._parse_dt(val)
                attrs[key] = parsed.isoformat() if parsed else val
            elif val is not None:
                attrs[key] = val
        attrs["repriseGraduellePossible"] = self.coordinator.data.get("repriseGraduellePossible", False)
        attrs["attribution"] = ATTRIBUTION
        return attrs


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor reporting the urgency level."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Niveau urgence"
        self._attr_unique_id = f"{entry.entry_id}_niveau_urgence"
        self._attr_icon = "mdi:alert-octagon"

    @property
    def native_value(self) -> str | None:
        """Return the human-readable urgency level."""
        interruption = self._get_current_interruption()
        if not interruption or "niveauUrgence" not in interruption:
            return None
        niveau = interruption.get("niveauUrgence")
        return NIVEAU_URGENCE_CODES.get(niveau, f"Inconnu ({niveau})") if niveau else None


class HydroPannesNombreClientSensor(HydroPannesSensorBase):
    """Sensor reporting the number of affected addresses."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
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
        return outage.get("nbClient")


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor reporting the effective start time."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Date début"
        self._attr_unique_id = f"{entry.entry_id}_date_debut"
        self._attr_icon = "mdi:clock-start"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the effective start time."""
        outage = self._get_current_interruption()
        if not outage:
            return None
        effective_debut, _ = self._get_effective_dates(outage)
        return effective_debut


class HydroPannesFinEstimeeSensor(HydroPannesSensorBase):
    """Sensor reporting the effective end time."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Date fin"
        self._attr_unique_id = f"{entry.entry_id}_datefin"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _get_end_time_info(self) -> tuple[datetime | None, bool, bool]:
        """Return (end_time, is_actual, is_postponed)."""
        outage = self._get_current_interruption()
        if not outage:
            return None, False, False
        if outage.get("etat") == "R":
            _, fin_report = self._get_effective_dates(outage)
            if fin_report:
                return fin_report, False, True
        date_fin = self._parse_dt(outage.get("dateFin"))
        if date_fin:
            return date_fin, True, False
        date_fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if date_fin_estimee:
            return date_fin_estimee, False, False
        return None, False, False

    @property
    def native_value(self) -> datetime | None:
        """Return the effective end time."""
        end_time, _, _ = self._get_end_time_info()
        return end_time

    @property
    def icon(self) -> str:
        """Return an icon reflecting the type of end time."""
        end_time, is_actual, is_postponed = self._get_end_time_info()
        if end_time is None:
            return "mdi:clock-end"
        if is_postponed:
            return "mdi:calendar-clock"
        if is_actual:
            return "mdi:clock-check"
        return "mdi:clock-alert"


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """Sensor reporting the current intervention step."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Statut intervention"
        self._attr_unique_id = f"{entry.entry_id}_statut_intervention"
        self._attr_icon = "mdi:account-hard-hat"

    @property
    def native_value(self) -> str | None:
        """Return the current intervention step label."""
        outage = self._get_current_interruption()
        if not outage:
            return None
        if self._is_outage_terminated(outage):
            return INFO_PANNES_STATES["service_retabli"]
        if outage.get("etat") == "R":
            return INFO_PANNES_STATES["aip_a_venir"]
        if self.coordinator.data and self.coordinator.data.get("repriseGraduellePossible"):
            return INFO_PANNES_STATES["reprise_graduelle"]
        code = outage.get("codeIntervention")
        niveau = outage.get("niveauUrgence")
        type_fin = outage.get("typeFinPrevue")
        if code == "L":
            return INTERVENTION_CODES_MAJEUR["L"] if niveau == "P" else INTERVENTION_CODES.get("L")
        if code in INTERVENTION_CODES:
            return INTERVENTION_CODES[code]
        if type_fin:
            return TYPE_FIN_PREVUE_CODES.get(type_fin, f"Inconnu ({type_fin})")
        return None


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """Sensor reporting the cause of the interruption."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Cause"
        self._attr_unique_id = f"{entry.entry_id}_cause"
        self._attr_icon = "mdi:help-circle-outline"

    @property
    def native_value(self) -> str | None:
        """Return the human-readable cause label."""
        outage = self._get_current_interruption()
        if not outage:
            return None
        code = outage.get("codeCause")
        if code is None:
            return "Indéterminée"
        code_str = str(code)
        cause_text = CAUSE_CODES.get(code_str)
        return f"{cause_text} ({code_str})" if cause_text else f"Inconnu ({code_str})"


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor reporting the interruption duration in seconds."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
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
        """Return the interruption duration in seconds."""
        outage = self._get_current_interruption()
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
                return round((date_fin - date_debut).total_seconds())
            return round((dt_util.now() - date_debut).total_seconds())
        except (ValueError, TypeError):
            _LOGGER.exception("Error calculating interruption duration")
            return None


class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor reporting time remaining until restoration in seconds."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Délai avant rétablissement"
        self._attr_unique_id = f"{entry.entry_id}_delai_avant_retablissement"
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_icon = "mdi:timer-sand"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return seconds until estimated restoration, or None."""
        outage = self._get_current_interruption()
        if not outage or self._is_outage_terminated(outage) or not self._is_outage_active(outage):
            return None
        date_fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if not date_fin_estimee:
            return None
        remaining = (date_fin_estimee - dt_util.now()).total_seconds()
        return round(remaining) if remaining >= 0 else None


class HydroPannesDerniereMAJSensor(HydroPannesSensorBase):
    """Sensor reporting the last update time."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Dernière MAJ"
        self._attr_unique_id = f"{entry.entry_id}_derniere_maj"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent update timestamp available."""
        interruption = self._get_current_interruption()
        if interruption and interruption.get("datePublication"):
            parsed = self._parse_dt(interruption.get("datePublication"))
            if parsed:
                return parsed
        if self.coordinator.data and "date" in self.coordinator.data:
            parsed = self._parse_dt(self.coordinator.data.get("date"))
            if parsed:
                return parsed
        if (
            hasattr(self.coordinator, "last_update_success_time")
            and self.coordinator.last_update_success_time
        ):
            val = self.coordinator.last_update_success_time
            return val if isinstance(val, datetime) else None
        return None


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Diagnostic sensor reporting the consumption location ID."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
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
        return self.coordinator.data.get("idLieuConso")
