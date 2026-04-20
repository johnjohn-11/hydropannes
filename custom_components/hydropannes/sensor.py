"""Support for Hydro-Pannes sensors."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
    StateType,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    CAUSE_CODES,
    CONF_NOM_LIEU,
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

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Entity description
# =============================================================================

@dataclass(frozen=True, kw_only=True)
class HydroPannesSensorEntityDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with per-sensor value/icon/attribute callables."""

    value_fn: Callable[[Any], StateType | datetime | None]
    attr_fn: Callable[[Any], dict[str, Any]] | None = None
    icon_fn: Callable[[Any], str | None] | None = None


# =============================================================================
# Module-level sensor logic functions
# =============================================================================

def _info_pannes_value(e: Any) -> str | None:
    """Return the service status string (matches HQ TYPE-DE-PANNES priority logic)."""
    if not e.coordinator.data:
        return None

    main_etat = e._get_main_etat()
    interruptions = e._get_interruptions()

    if not interruptions:
        if main_etat == "A":
            return INFO_PANNES_STATES["aucune_panne"]
        if main_etat == "N":
            return INFO_PANNES_STATES["panne_en_cours"]
        return None

    # Priority 1: gradual restoration
    active_outage = e._get_active_outage()
    if active_outage and e.coordinator.data.get("repriseGraduellePossible"):
        return INFO_PANNES_STATES["reprise_graduelle"]

    # Priority 2: active non-planned outage
    if active_outage:
        if active_outage.get("niveauUrgence") == "P":
            return INFO_PANNES_STATES["panne_majeure"]
        return INFO_PANNES_STATES["panne_en_cours"]

    # Priority 3: terminated non-planned outage
    # A non-cancelled, non-terminated AIP supersedes a past outage.
    terminated_outage = e._get_terminated_outage()
    if terminated_outage:
        planned_check = e._get_planned_intervention()
        if (
            not planned_check
            or e._is_aip_annulee(planned_check)
            or e._is_outage_terminated(planned_check)
        ):
            return INFO_PANNES_STATES["service_retabli"]

    # Priority 4: planned intervention
    planned = e._get_planned_intervention()
    if planned:
        if e._is_aip_annulee(planned):
            return INFO_PANNES_STATES["aip_annulee"]
        if e._is_outage_terminated(planned):
            return INFO_PANNES_STATES["aip_terminee"]
        if main_etat == "N":
            return INFO_PANNES_STATES["aip_en_cours"]
        return INFO_PANNES_STATES["aip_a_venir"]

    if main_etat == "A":
        return INFO_PANNES_STATES["aucune_panne"]
    if main_etat == "N":
        return INFO_PANNES_STATES["panne_en_cours"]
    return None


def _info_pannes_icon(e: Any) -> str:
    """Return an icon matching the current service status."""
    state = _info_pannes_value(e)
    if state == INFO_PANNES_STATES["aucune_panne"]:
        return "mdi:check-circle"
    if state in (INFO_PANNES_STATES["service_retabli"], INFO_PANNES_STATES["aip_terminee"]):
        return "mdi:check-circle-outline"
    if state in (
        INFO_PANNES_STATES["aip_a_venir"],
        INFO_PANNES_STATES["aip_en_cours"],
        INFO_PANNES_STATES["aip_annulee"],
    ):
        return "mdi:calendar-clock"
    if state == INFO_PANNES_STATES["panne_majeure"]:
        return "mdi:alert-octagon"
    if state == INFO_PANNES_STATES["reprise_graduelle"]:
        return "mdi:restore-alert"
    if state == INFO_PANNES_STATES["panne_en_cours"]:
        return "mdi:alert-circle"
    return "mdi:help-circle"


def _info_pannes_attrs(e: Any) -> dict[str, Any]:
    """Return key fields from the selected interruption as extra attributes."""
    if not e.coordinator.data:
        return {}

    interruptions = e._get_interruptions()
    if not interruptions:
        return {"attribution": ATTRIBUTION}

    inter = e._get_current_interruption()
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
            parsed = e._parse_dt(val)
            attrs[key] = parsed.isoformat() if parsed else val
        elif val is not None:
            attrs[key] = val

    attrs["repriseGraduellePossible"] = e.coordinator.data.get("repriseGraduellePossible", False)
    attrs["attribution"] = ATTRIBUTION
    return attrs


def _niveau_urgence_value(e: Any) -> str | None:
    """Return the human-readable urgency level."""
    interruption = e._get_current_interruption()
    if not interruption or "niveauUrgence" not in interruption:
        return None
    niveau = interruption.get("niveauUrgence")
    return NIVEAU_URGENCE_CODES.get(niveau, f"Inconnu ({niveau})") if niveau else None


def _debut_value(e: Any) -> datetime | None:
    """Return the effective start time (uses dateDebutReport for postponed interventions)."""
    outage = e._get_current_interruption()
    if not outage:
        return None
    effective_debut, _ = e._get_effective_dates(outage)
    return effective_debut


def _fin_estimee_info(e: Any) -> tuple[datetime | None, bool, bool]:
    """Return (end_time, is_actual, is_postponed) for the current interruption."""
    outage = e._get_current_interruption()
    if not outage:
        return None, False, False
    if outage.get("etat") == "R":
        _, fin_report = e._get_effective_dates(outage)
        if fin_report:
            return fin_report, False, True
    date_fin = e._parse_dt(outage.get("dateFin"))
    if date_fin:
        return date_fin, True, False
    date_fin_estimee = e._parse_dt(outage.get("dateFinEstimeeMax"))
    if date_fin_estimee:
        return date_fin_estimee, False, False
    return None, False, False


def _fin_estimee_value(e: Any) -> datetime | None:
    """Return the effective end time."""
    end_time, _, _ = _fin_estimee_info(e)
    return end_time


def _fin_estimee_icon(e: Any) -> str:
    """Return an icon reflecting the type of end time."""
    end_time, is_actual, is_postponed = _fin_estimee_info(e)
    if end_time is None:
        return "mdi:clock-end"
    if is_postponed:
        return "mdi:calendar-clock"
    if is_actual:
        return "mdi:clock-check"
    return "mdi:clock-alert"


def _statut_intervention_value(e: Any) -> str | None:
    """Return the current intervention step label (matches HQ ETAPE-PANNE)."""
    outage = e._get_current_interruption()
    if not outage:
        return None
    if e._is_outage_terminated(outage):
        return INFO_PANNES_STATES["service_retabli"]
    if outage.get("etat") == "R":
        return INFO_PANNES_STATES["aip_a_venir"]
    if e.coordinator.data and e.coordinator.data.get("repriseGraduellePossible"):
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


def _cause_value(e: Any) -> str | None:
    """Return the human-readable cause label with raw code."""
    outage = e._get_current_interruption()
    if not outage:
        return None
    code = outage.get("codeCause")
    if code is None:
        return "Indéterminée"
    code_str = str(code)
    cause_text = CAUSE_CODES.get(code_str)
    return f"{cause_text} ({code_str})" if cause_text else f"Inconnu ({code_str})"


def _duree_value(e: Any) -> int | None:
    """Return the interruption duration in seconds."""
    outage = e._get_current_interruption()
    if not outage or "dateDebut" not in outage:
        return None
    try:
        date_debut = e._parse_dt(outage["dateDebut"])
        if not date_debut:
            return None
        if outage.get("dateFin"):
            date_fin = e._parse_dt(outage["dateFin"])
            if not date_fin:
                return None
            return round((date_fin - date_debut).total_seconds())
        return round((dt_util.now() - date_debut).total_seconds())
    except (ValueError, TypeError):
        _LOGGER.exception("Error calculating interruption duration")
        return None


def _duree_avant_retablissement_value(e: Any) -> int | None:
    """Return seconds until the estimated restoration time, or None."""
    outage = e._get_current_interruption()
    if not outage or e._is_outage_terminated(outage) or not e._is_outage_active(outage):
        return None
    date_fin_estimee = e._parse_dt(outage.get("dateFinEstimeeMax"))
    if not date_fin_estimee:
        return None
    remaining = (date_fin_estimee - dt_util.now()).total_seconds()
    return round(remaining) if remaining >= 0 else None


def _derniere_maj_value(e: Any) -> datetime | None:
    """Return the most recent update timestamp available.

    Priority:
      1. datePublication from the selected interruption.
      2. Top-level 'date' field from the API response.
      3. Time of the coordinator's last successful refresh.
    """
    interruption = e._get_current_interruption()
    if interruption and interruption.get("datePublication"):
        parsed = e._parse_dt(interruption.get("datePublication"))
        if parsed:
            return parsed
    if e.coordinator.data and "date" in e.coordinator.data:
        parsed = e._parse_dt(e.coordinator.data.get("date"))
        if parsed:
            return parsed
    if (
        hasattr(e.coordinator, "last_update_success_time")
        and e.coordinator.last_update_success_time
    ):
        val = e.coordinator.last_update_success_time
        return val if isinstance(val, datetime) else None
    return None


def _lieu_conso_value(e: Any) -> str | None:
    """Return the consumption location ID."""
    if not e.coordinator.data:
        return None
    return e.coordinator.data.get("idLieuConso")


# =============================================================================
# Sensor descriptions
# =============================================================================

SENSOR_DESCRIPTIONS: tuple[HydroPannesSensorEntityDescription, ...] = (
    HydroPannesSensorEntityDescription(
        key="info_pannes",
        name="Info-pannes",
        icon="mdi:information-outline",
        value_fn=_info_pannes_value,
        attr_fn=_info_pannes_attrs,
        icon_fn=_info_pannes_icon,
    ),
    HydroPannesSensorEntityDescription(
        key="niveau_urgence",
        name="Niveau urgence",
        icon="mdi:alert-octagon",
        value_fn=_niveau_urgence_value,
    ),
    HydroPannesSensorEntityDescription(
        key="nbclient",
        name="Adresses touchées",
        icon="mdi:account-multiple",
        native_unit_of_measurement="clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e._get_current_interruption().get("nbClient")
        if e._get_current_interruption()
        else None,
    ),
    HydroPannesSensorEntityDescription(
        key="date_debut",
        name="Date début",
        icon="mdi:clock-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_debut_value,
    ),
    HydroPannesSensorEntityDescription(
        key="datefin",
        name="Date fin",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_fin_estimee_value,
        icon_fn=_fin_estimee_icon,
    ),
    HydroPannesSensorEntityDescription(
        key="statut_intervention",
        name="Statut intervention",
        icon="mdi:account-hard-hat",
        value_fn=_statut_intervention_value,
    ),
    HydroPannesSensorEntityDescription(
        key="cause",
        name="Cause",
        icon="mdi:help-circle-outline",
        value_fn=_cause_value,
    ),
    HydroPannesSensorEntityDescription(
        key="duree",
        name="Durée",
        icon="mdi:timer-outline",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_duree_value,
    ),
    HydroPannesSensorEntityDescription(
        key="duree_avant_retablissement",
        name="Durée avant rétablissement",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_duree_avant_retablissement_value,
    ),
    HydroPannesSensorEntityDescription(
        key="derniere_maj",
        name="Dernière MAJ",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_derniere_maj_value,
    ),
    HydroPannesSensorEntityDescription(
        key="idlieuconso",
        name="Lieu consommation",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_lieu_conso_value,
    ),
)


# =============================================================================
# Base and generic sensor classes
# =============================================================================

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


class HydroPannesSensor(HydroPannesSensorBase):
    """Generic Hydro-Pannes sensor driven by a HydroPannesSensorEntityDescription."""

    entity_description: HydroPannesSensorEntityDescription

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
        description: HydroPannesSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType | datetime | None:
        """Return the sensor value via the description's value_fn."""
        return self.entity_description.value_fn(self)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes via the description's attr_fn, if defined."""
        if self.entity_description.attr_fn:
            return self.entity_description.attr_fn(self)
        return {}

    @property
    def icon(self) -> str | None:
        """Return the icon via the description's icon_fn, or fall back to static icon."""
        if self.entity_description.icon_fn:
            return self.entity_description.icon_fn(self)
        return self.entity_description.icon


# =============================================================================
# Platform setup
# =============================================================================

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes sensors for a config entry."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]

    async_add_entities(
        HydroPannesSensor(coordinator, entry, nom_lieu, description)
        for description in SENSOR_DESCRIPTIONS
    )
