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
    ATTRIBUTION,
    CAUSE_CODES,
    CAUSE_OPTIONS,
    DOMAIN,
    INFO_PANNES_OPTIONS,
    INTERVENTION_CODES,
    INTERVENTION_CODES_MAJEUR,
    NIVEAU_URGENCE_CODES,
    NIVEAU_URGENCE_OPTIONS,
    STATUT_INTERVENTION_OPTIONS,
    TYPE_FIN_PREVUE_CODES,
)
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import HydroPannesConfigEntry

_LOGGER = logging.getLogger(__name__)

# Entities are updated by the coordinator; no parallel polling needed.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydroPannesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes sensors for a config entry."""
    coordinator = entry.runtime_data
    nom_lieu = entry.title

    async_add_entities(
        [
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
    )


class HydroPannesSensorBase(
    HydroPannesHelperMixin,
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    SensorEntity,
):
    """Base class for all Hydro-Pannes sensors."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
        # Device identity is fixed for the entity's lifetime; set it once here
        # rather than rebuilding a DeviceInfo on every property access.
        # The device is named after the location alone: Home Assistant already
        # shows the integration name around it, and with has_entity_name the
        # device name prefixes every entity name.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=nom_lieu,
            manufacturer="Hydro-Québec",
            model="Info-pannes",
        )

    @property
    def available(self) -> bool:
        """Return True only when the coordinator has successfully fetched data."""
        return super().available and self.coordinator.data is not None


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """Sensor reporting the overall service status.

    The state is a language-neutral slug from INFO_PANNES_OPTIONS; the labels
    shown in the UI come from the translation files. Per-state icons live in
    icons.json.
    """

    _attr_translation_key = "info_pannes"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = INFO_PANNES_OPTIONS

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_info_pannes"

    @property
    def native_value(self) -> str | None:
        """Return the service status string."""
        if not self.coordinator.data:
            return None

        main_etat = self._get_main_etat()
        interruptions = self._get_interruptions()

        if not interruptions:
            if main_etat == "A":
                return "aucune_panne"
            if main_etat == "N":
                return "panne_en_cours"
            return None

        active_outage = self._get_active_outage()
        if active_outage and self._is_reprise_graduelle(active_outage):
            return "reprise_graduelle"

        if active_outage:
            if active_outage.get("niveauUrgence") == "P":
                return "panne_majeure"
            return "panne_en_cours"

        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            planned_check = self._get_planned_intervention()
            if not self._planned_supersedes_terminated(planned_check):
                return "service_retabli"

        planned = self._get_planned_intervention()
        if planned:
            if self._is_aip_reportee(planned):
                return "aip_reportee"
            if self._is_aip_annulee(planned):
                return "aip_annulee"
            if self._is_outage_terminated(planned):
                return "aip_terminee"
            if main_etat == "N":
                return "aip_en_cours"
            return "aip_a_venir"

        if main_etat == "A":
            return "aucune_panne"
        if main_etat == "N":
            return "panne_en_cours"
        return None


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor reporting the urgency level."""

    _attr_translation_key = "niveau_urgence"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = NIVEAU_URGENCE_OPTIONS

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_niveau_urgence"

    @property
    def native_value(self) -> str | None:
        """Return the urgency level slug, or None if HQ reports none.

        An unrecognized code yields None rather than a made-up state: Home
        Assistant rejects any value outside _attr_options.
        """
        interruption = self._get_current_interruption()
        if not interruption:
            return None
        niveau = interruption.get("niveauUrgence")
        if not niveau:
            return None
        return NIVEAU_URGENCE_CODES.get(niveau)


class HydroPannesNombreClientSensor(HydroPannesSensorBase):
    """Sensor reporting the number of affected addresses."""

    _attr_translation_key = "adresses_touchees"
    _attr_native_unit_of_measurement = "clients"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_nbclient"

    @property
    def native_value(self) -> int | None:
        """Return the number of affected clients."""
        outage = self._get_current_interruption()
        if not outage:
            return None
        return outage.get("nbClient")


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor reporting the effective start time."""

    _attr_translation_key = "date_debut"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_date_debut"

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

    _attr_translation_key = "date_fin"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_datefin"

    def _get_end_time_info(self) -> tuple[datetime | None, bool, bool]:
        """Return (end_time, is_actual, is_postponed)."""
        outage = self._get_current_interruption()
        if not outage:
            return None, False, False
        if outage.get("etat") == "R" or self._is_aip_reportee(outage):
            _, fin_report = self._get_effective_dates(outage)
            if fin_report:
                return fin_report, False, True
            # dateFinReport absent — don't fall through to the cancelled dateFin
            return None, False, True
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

    _attr_translation_key = "statut_intervention"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUT_INTERVENTION_OPTIONS

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_statut_intervention"

    @property
    def native_value(self) -> str | None:
        """Return the current intervention step slug.

        An unrecognized typeFinPrevue yields None rather than a made-up state:
        Home Assistant rejects any value outside _attr_options.
        """
        outage = self._get_current_interruption()
        if not outage:
            return None
        if self._is_outage_terminated(outage):
            return "service_retabli"
        if self._is_aip_reportee(outage):
            return "aip_reportee"
        if outage.get("etat") == "R":
            return "aip_a_venir"
        if self._is_reprise_graduelle(outage):
            return "reprise_graduelle"
        code = outage.get("codeIntervention")
        niveau = outage.get("niveauUrgence")
        type_fin = outage.get("typeFinPrevue")
        if code == "L":
            return INTERVENTION_CODES_MAJEUR["L"] if niveau == "P" else INTERVENTION_CODES["L"]
        if code in INTERVENTION_CODES:
            return INTERVENTION_CODES[code]
        if type_fin:
            return TYPE_FIN_PREVUE_CODES.get(type_fin)
        return None


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """Sensor reporting the cause of the interruption."""

    _attr_translation_key = "cause"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CAUSE_OPTIONS

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_cause"

    @property
    def native_value(self) -> str | None:
        """Return the cause slug.

        "indeterminee" when Hydro-Québec reports no code at all, "inconnue"
        when it reports a code this integration does not know yet. The raw
        code is kept in the code_cause attribute either way.
        """
        outage = self._get_current_interruption()
        if not outage:
            return None
        code = outage.get("codeCause")
        if code is None:
            return "indeterminee"
        return CAUSE_CODES.get(str(code), "inconnue")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw HQ cause code.

        Several codes map onto a single slug, so the code is kept as an
        attribute to preserve the distinction the state no longer carries.
        """
        outage = self._get_current_interruption()
        if not outage:
            return {}
        code = outage.get("codeCause")
        if code is None:
            return {}
        return {"code_cause": str(code)}


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor reporting the interruption duration in seconds."""

    _attr_translation_key = "duree"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    # No state_class: the value grows with wall-clock time during an outage and
    # resets between outages, so long-term statistics would be a meaningless
    # sawtooth. It remains useful as a live state.

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_duree"

    @property
    def native_value(self) -> int | None:
        """Return the interruption duration in seconds.

        Uses the effective start/end dates so postponed or rescheduled AIPs
        are measured against their real (rescheduled) window rather than the
        cancelled original slot. Returns None when the interruption has not
        started yet (e.g. an upcoming planned intervention), which avoids
        reporting a negative duration. When the interruption is ongoing (no
        effective end date), the elapsed time up to now is returned.
        """
        outage = self._get_current_interruption()
        if not outage:
            return None
        try:
            effective_debut, effective_fin = self._get_effective_dates(outage)
            if not effective_debut or self._is_date_in_future(effective_debut):
                return None
            end = effective_fin or dt_util.now()
            return max(round((end - effective_debut).total_seconds()), 0)
        except (ValueError, TypeError):
            _LOGGER.exception("Error calculating interruption duration")
            return None


class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor reporting time remaining until restoration in seconds."""

    _attr_translation_key = "delai_avant_retablissement"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    # No state_class: this countdown shifts every poll and resets between
    # outages, so long-term statistics would be a meaningless sawtooth.

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_delai_avant_retablissement"

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

    _attr_translation_key = "derniere_maj"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_derniere_maj"

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent update timestamp available."""
        interruption = self._get_current_interruption()
        if interruption and interruption.get("datePublication"):
            parsed = self._parse_dt(interruption.get("datePublication"))
            if parsed:
                return parsed
        # Outside an outage there is no datePublication, so fall back to the
        # time of the last successful poll.
        return self.coordinator.last_success_time


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Diagnostic sensor reporting the consumption location ID."""

    _attr_translation_key = "lieu_consommation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_idlieuconso"

    @property
    def native_value(self) -> str | None:
        """Return the consumption location ID."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("idLieuConso")
