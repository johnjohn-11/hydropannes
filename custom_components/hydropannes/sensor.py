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
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CAUSE_CODES,
    CONF_NOM_LIEU,
    DOMAIN,
    INFO_PANNES_STATES,
    INTERVENTION_CODES,
    INTERVENTION_CODES_MAJEUR,
    NIVEAU_URGENCE_CODES,
    SIGNAL_NEW_COORDINATOR,
    TYPE_FIN_PREVUE_CODES,
)
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

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
    """Set up Hydro-Pannes sensors for a config entry."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.data[CONF_NOM_LIEU]

    sensors: list[HydroPannesSensorBase] = [
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
        HydroPannesSommaireSensor(coordinator, entry, nom_lieu),
    ]

    async_add_entities(sensors)


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
    """Sensor reporting the overall service status.

    State logic (priority order, matching HQ TYPE-DE-PANNES):

    1. Gradual restoration (GRAP):
       repriseGraduellePossible = True AND active outage present
       → "Rétablissement graduel du service en cours"

    2. Active non-planned outage:
       main etat = "N", interruptionPlanifiee = False
       niveauUrgence = "P" → "Panne majeure en cours"
       otherwise          → "Panne en cours"

    3. Terminated non-planned outage:
       dateFin in the past (and no superseding AIP)
       → "Service rétabli"

    4. Planned intervention (AIP):
       etat = "A" or codeRemarque = "92" → "Interruption planifiée annulée"
       dateFin in the past                → "Interruption planifiée terminée"
       main etat = "N"                    → "Interruption planifiée en cours"
       effective dateDebut in the future  → "Interruption planifiée à venir"

    Fallback:
       main etat = "A"  → "Aucune panne détectée"
       main etat = "N"  → "Panne en cours"
       otherwise        → None
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

        # Priority 1: gradual restoration
        active_outage = self._get_active_outage()
        if active_outage and self.coordinator.data.get("repriseGraduellePossible"):
            return INFO_PANNES_STATES["reprise_graduelle"]

        # Priority 2: active non-planned outage
        if active_outage:
            niveau = active_outage.get("niveauUrgence")
            if niveau == "P":
                return INFO_PANNES_STATES["panne_majeure"]
            return INFO_PANNES_STATES["panne_en_cours"]

        # Priority 3: terminated non-planned outage
        # A non-cancelled, non-terminated AIP supersedes a past outage.
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            planned_check = self._get_planned_intervention()
            if (
                not planned_check
                or self._is_aip_annulee(planned_check)
                or self._is_outage_terminated(planned_check)
            ):
                return INFO_PANNES_STATES["service_retabli"]
            # Fall through to Priority 4 to display the AIP state.

        # Priority 4: planned intervention
        planned = self._get_planned_intervention()
        if planned:
            if self._is_aip_annulee(planned):
                return INFO_PANNES_STATES["aip_annulee"]
            if self._is_outage_terminated(planned):
                return INFO_PANNES_STATES["aip_terminee"]
            if main_etat == "N":
                return INFO_PANNES_STATES["aip_en_cours"]
            return INFO_PANNES_STATES["aip_a_venir"]

        # Fallback
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
        if state in (
            INFO_PANNES_STATES["service_retabli"],
            INFO_PANNES_STATES["aip_terminee"],
        ):
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the selected interruption as extra attributes."""
        if not self.coordinator.data:
            return {}

        interruptions = self._get_interruptions()
        if not interruptions:
            return {"attribution": "Données fournies par Hydro-Québec"}

        inter = self._get_current_interruption()
        if not inter:
            return {"attribution": "Données fournies par Hydro-Québec"}

        attrs: dict[str, Any] = {}
        for key in (
            "dateDebut",
            "dateFin",
            "etat",
            "dateFinEstimeeMin",
            "dateFinEstimeeMax",
            "dateDebutReport",
            "dateFinReport",
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
            "typeFinPrevue",
        ):
            val = inter.get(key)
            if key.startswith("date") and val:
                parsed = self._parse_dt(val)
                attrs[key] = parsed.isoformat() if parsed else val
            elif val is not None:
                attrs[key] = val

        attrs["repriseGraduellePossible"] = self.coordinator.data.get(
            "repriseGraduellePossible", False
        )
        attrs["attribution"] = "Données fournies par Hydro-Québec"
        return attrs


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor reporting the urgency level of the current interruption.

    "N" → "Normal", "P" → "Panne majeure", unknown code → "Inconnu (code)".
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
        """Return the human-readable urgency level."""
        interruption = self._get_current_interruption()

        if not interruption or "niveauUrgence" not in interruption:
            return None

        niveau = interruption.get("niveauUrgence")
        if niveau is None:
            return None
        return NIVEAU_URGENCE_CODES.get(niveau, f"Inconnu ({niveau})")


class HydroPannesNombreClientSensor(HydroPannesSensorBase):
    """Sensor reporting the number of addresses affected by the current interruption."""

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

        return outage.get("nbClient")


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor reporting the effective start time of the current interruption.

    Returns dateDebutReport for postponed planned interventions (etat = "R"),
    otherwise returns dateDebut.
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
        """Return the effective start time."""
        outage = self._get_current_interruption()

        if not outage:
            return None

        effective_debut, _ = self._get_effective_dates(outage)
        return effective_debut


class HydroPannesFinEstimeeSensor(HydroPannesSensorBase):
    """Sensor reporting the effective end time of the current interruption.

    Value priority:
      1. dateFin / dateFinReport — actual or confirmed end time.
      2. dateFinEstimeeMax       — estimated end time.

    Icons reflect whether the time is actual, estimated, or postponed.
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

    def _get_end_time_info(self) -> tuple[datetime | None, bool, bool]:
        """Return (end_time, is_actual, is_postponed) for the current interruption."""
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
    """Sensor reporting the current intervention step, matching HQ ETAPE-PANNE.

    Steps (in order):
      1. Début de la panne (dateDebut present)
      2. Évaluation des travaux requis        (codeIntervention = "N")
      3. Équipe désignée                      (codeIntervention = "A" or "R")
      4. Travaux en cours sur le réseau       (codeIntervention = "L", normal urgency)
         Réalisation des travaux par priorité (codeIntervention = "L", niveauUrgence = "P")
      5. Rétablissement en évaluation         (typeFinPrevue = "U")
         Rétablissement prévu                 (typeFinPrevue = "D" or "P")
         Rétablissement graduel               (repriseGraduellePossible = True)
      → Service rétabli                       (dateFin in the past)
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
        """Return the current intervention step label."""
        outage = self._get_current_interruption()

        if not outage:
            return None

        if self._is_outage_terminated(outage):
            return INFO_PANNES_STATES["service_retabli"]

        if outage.get("etat") == "R":
            return INFO_PANNES_STATES["aip_a_venir"]

        if self.coordinator.data and self.coordinator.data.get(
            "repriseGraduellePossible"
        ):
            return INFO_PANNES_STATES["reprise_graduelle"]

        code = outage.get("codeIntervention")
        niveau = outage.get("niveauUrgence")
        type_fin = outage.get("typeFinPrevue")

        if code == "L":
            if niveau == "P":
                return INTERVENTION_CODES_MAJEUR["L"]
            return INTERVENTION_CODES.get("L")

        if code in INTERVENTION_CODES:
            return INTERVENTION_CODES[code]

        if type_fin:
            return TYPE_FIN_PREVUE_CODES.get(type_fin, f"Inconnu ({type_fin})")

        return None


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """Sensor reporting the cause of the current interruption."""

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
        """Return the human-readable cause label with raw code."""
        outage = self._get_current_interruption()

        if not outage:
            return None

        code = outage.get("codeCause")
        if code is None:
            return "Indéterminée"

        code_str = str(code)
        cause_text = CAUSE_CODES.get(code_str)
        if cause_text:
            return f"{cause_text} ({code_str})"
        return f"Inconnu ({code_str})"


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor reporting the duration of the current interruption in seconds.

    Uses dateFin − dateDebut for terminated outages, or now − dateDebut
    for ongoing ones.
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
                duration_seconds = (date_fin - date_debut).total_seconds()
            else:
                duration_seconds = (dt_util.now() - date_debut).total_seconds()

            return round(duration_seconds)
        except (ValueError, TypeError):
            _LOGGER.exception("Error calculating interruption duration")
            return None


class HydroPannesDureeAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor reporting the time remaining until power restoration, in seconds.

    Returns a value only for active outages (planned or unplanned) that have
    a dateFinEstimeeMax. Returns None once the outage is terminated or the
    estimated end time has passed.
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
        """Return seconds until the estimated restoration time, or None."""
        outage = self._get_current_interruption()

        if not outage or self._is_outage_terminated(outage):
            return None

        if not self._is_outage_active(outage):
            return None

        date_fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if not date_fin_estimee:
            return None

        remaining = (date_fin_estimee - dt_util.now()).total_seconds()
        return round(remaining) if remaining >= 0 else None


class HydroPannesDerniereMAJSensor(HydroPannesSensorBase):
    """Sensor reporting the last update time for the current interruption."""

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
        """Return the most recent update timestamp available.

        Priority:
          1. datePublication from the selected interruption.
          2. Top-level 'date' field from the API response.
          3. Time of the coordinator's last successful refresh.
        """
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
            return self.coordinator.last_update_success_time

        return None


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Diagnostic sensor reporting the consumption location ID (idLieuConso)."""

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

        return self.coordinator.data.get("idLieuConso")


class HydroPannesSommaireSensor(HydroPannesSensorBase):
    """Sensor aggregating the outage state across all configured locations.

    Useful when monitoring multiple sites (e.g. home and cottage). Shows a
    human-readable summary such as "2 pannes actives sur 3 lieux".

    Each configured location creates its own instance of this sensor, but all
    instances reflect the same global state. Users with multiple locations
    should enable one instance and disable the rest.

    Disabled by default — opt in via the entity registry.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the summary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Sommaire"
        self._attr_unique_id = f"{entry.entry_id}_sommaire"
        self._attr_icon = "mdi:map-marker-multiple"
        self._unsub_coordinators: list[Any] = []
        self._unsub_signal: Any = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to all current coordinators and the new-coordinator signal."""
        await super().async_added_to_hass()
        self._resubscribe_all()
        self._unsub_signal = async_dispatcher_connect(
            self.hass, SIGNAL_NEW_COORDINATOR, self._on_coordinators_changed
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from all coordinators and the dispatcher signal."""
        for unsub in self._unsub_coordinators:
            unsub()
        if self._unsub_signal:
            self._unsub_signal()

    def _resubscribe_all(self) -> None:
        """Replace existing coordinator subscriptions with the current set.

        Skips the entity's own coordinator (already handled by CoordinatorEntity).
        """
        for unsub in self._unsub_coordinators:
            unsub()
        self._unsub_coordinators = [
            coord.async_add_listener(self.async_write_ha_state)
            for coord in self.hass.data.get(DOMAIN, {}).values()
            if isinstance(coord, HydroPannesDataUpdateCoordinator)
            and coord is not self.coordinator
        ]

    @callback
    def _on_coordinators_changed(self) -> None:
        """Re-subscribe and refresh state when locations are added or removed."""
        self._resubscribe_all()
        self.async_write_ha_state()

    def _all_coordinators(self) -> list[HydroPannesDataUpdateCoordinator]:
        """Return all active coordinators from the HA data store."""
        return [
            c for c in self.hass.data.get(DOMAIN, {}).values()
            if isinstance(c, HydroPannesDataUpdateCoordinator)
        ]

    @property
    def native_value(self) -> str:
        """Return a human-readable summary of outage state across all locations."""
        coordinators = self._all_coordinators()
        total = len(coordinators)
        active = sum(
            1 for c in coordinators if c.data and c.data.get("etat") == "N"
        )

        lieux_label = f"lieu{'x' if total > 1 else ''}"
        surveille_label = f"surveillé{'s' if total > 1 else ''}"

        if active == 0:
            return f"Aucune panne — {total} {lieux_label} {surveille_label}"

        pannes_label = f"panne{'s' if active > 1 else ''} active{'s' if active > 1 else ''}"
        return f"{active} {pannes_label} sur {total} {lieux_label}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-location outage state and aggregate counts."""
        coordinators = self._all_coordinators()
        active_count = sum(
            1 for c in coordinators if c.data and c.data.get("etat") == "N"
        )

        lieux: list[dict[str, Any]] = []
        for coord in coordinators:
            info: dict[str, Any] = {
                "lieu_conso": f"****{coord.lieu_conso[-4:]}",
                "etat": coord.data.get("etat") if coord.data else None,
                "en_panne": bool(coord.data and coord.data.get("etat") == "N"),
            }
            if (
                hasattr(coord, "last_update_success_time")
                and coord.last_update_success_time
            ):
                info["derniere_maj"] = coord.last_update_success_time.isoformat()
            lieux.append(info)

        return {
            "total_lieux": len(coordinators),
            "lieux_en_panne": active_count,
            "lieux": lieux,
            "attribution": "Données fournies par Hydro-Québec",
        }
