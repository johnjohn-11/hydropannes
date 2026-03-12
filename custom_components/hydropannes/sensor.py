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
    INFO_PANNES_STATES,
    INTERVENTION_CODES,
    INTERVENTION_CODES_MAJEUR,
    NIVEAU_URGENCE_CODES,
    TYPE_FIN_PREVUE_CODES,
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
        HydroPannesEtatAPIBrutSensor(coordinator, entry, nom_lieu),
        HydroPannesEtatInterruptionSensor(coordinator, entry, nom_lieu),
        HydroPannesCodeInterventionSensor(coordinator, entry, nom_lieu),
        HydroPannesTypeFinPrevueSensor(coordinator, entry, nom_lieu),
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
        - AND effective dateDebut is in the future (uses report date if postponed)
        """
        if not self._is_planned_intervention(intr):
            return False

        effective_debut, _ = self._get_effective_dates(intr)
        return self._is_date_in_future(effective_debut)

    def _get_effective_dates(
        self, intr: dict[str, Any]
    ) -> tuple[datetime | None, datetime | None]:
        """Return effective start/end dates for a planned intervention.

        If etat = "R" (postponed), use dateDebutReport/dateFinReport.
        Otherwise use dateDebut/dateFin.

        Returns: (effective_debut, effective_fin)
        """
        if intr.get("etat") == "R":
            debut = self._parse_dt(intr.get("dateDebutReport"))
            fin = self._parse_dt(intr.get("dateFinReport"))
            # Fall back to original if report dates are missing
            if debut:
                return debut, fin
        return (
            self._parse_dt(intr.get("dateDebut")),
            self._parse_dt(intr.get("dateFin")),
        )

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

    Logic (in priority order) — matches HQ TYPE-DE-PANNES exactly:
    -------------------------
    PRIORITY 1 - Rétablissement graduel (GRAP):
      - repriseGraduellePossible = True AND active outage
      -> "Rétablissement graduel du service en cours"

    PRIORITY 2 - Active non-planned outage:
      - Main etat = "N", interruptionPlanifiee = False
      - If niveauUrgence = "P" -> "Panne majeure en cours"
      - Otherwise -> "Panne en cours"

    PRIORITY 3 - Terminated non-planned outage:
      - dateFin exists and in the past
      -> "Service rétabli"

    PRIORITY 4 - Planned intervention:
      - interruptionPlanifiee = True
      - If annulée (codeRemarque = "A" or etat = "A") -> "Interruption planifiée annulée"
      - If dateFin in past -> "Interruption planifiée terminée"
      - If main etat = "N" -> "Interruption planifiée en cours"
      - If dateDebut in future -> "Interruption planifiée à venir"
      -> "Interruption planifiée à venir" (generic)

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

    def _is_aip_annulee(self, intr: dict[str, Any]) -> bool:
        """Check if a planned interruption is cancelled."""
        return intr.get("etat") == "A" or str(intr.get("codeRemarque", "")) == "A"

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
                return INFO_PANNES_STATES["aucune_panne"]
            if main_etat == "N":
                return INFO_PANNES_STATES["panne_en_cours"]
            return None

        # PRIORITY 1: Rétablissement graduel (GRAP)
        active_outage = self._get_active_outage()
        if active_outage and self.coordinator.data.get("repriseGraduellePossible"):
            return INFO_PANNES_STATES["reprise_graduelle"]

        # PRIORITY 2: Active non-planned outage
        if active_outage:
            niveau = active_outage.get("niveauUrgence")
            if niveau == "P":
                return INFO_PANNES_STATES["panne_majeure"]
            return INFO_PANNES_STATES["panne_en_cours"]

        # PRIORITY 3: Terminated non-planned outage
        terminated_outage = self._get_terminated_outage()
        if terminated_outage:
            return INFO_PANNES_STATES["service_retabli"]

        # PRIORITY 4: Planned intervention
        planned = self._get_planned_intervention()
        if planned:
            if self._is_aip_annulee(planned):
                return INFO_PANNES_STATES["aip_annulee"]
            if self._is_outage_terminated(planned):
                return INFO_PANNES_STATES["aip_terminee"]
            if main_etat == "N":
                return INFO_PANNES_STATES["aip_en_cours"]
            if self._is_future_planned(planned):
                return INFO_PANNES_STATES["aip_a_venir"]
            return INFO_PANNES_STATES["aip_a_venir"]

        # FALLBACK
        if main_etat == "A":
            return INFO_PANNES_STATES["aucune_panne"]
        if main_etat == "N":
            return INFO_PANNES_STATES["panne_en_cours"]

        return None

    @property
    def icon(self) -> str:
        """Return the icon based on current state."""
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
        """Return extra attributes from the active interruption."""
        if not self.coordinator.data:
            return {}

        interruptions = self._get_interruptions()
        if not interruptions:
            return {"attribution": "Données fournies par Hydro-Québec"}

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
    """Sensor for urgency level.

    Values:
      - "N" -> "Normal"
      - "P" -> "Panne majeure"
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
        if niveau is None:
            return None
        return NIVEAU_URGENCE_CODES.get(niveau, f"Inconnu ({niveau})")


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

        return outage.get("nbClient")


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor for outage/interruption start time.

    For postponed planned interruptions (etat = "R"), returns dateDebutReport.
    Otherwise returns dateDebut.
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
    """Sensor for estimated or actual end time.

    For postponed planned interruptions (etat = "R"), returns dateFinReport.
    Sub-priority for value:
      1. dateFin / dateFinReport (actual or postponed end)
      2. dateFinEstimeeMax (estimated end)

    Icons:
      - mdi:clock-check  (actual end time - dateFin)
      - mdi:clock-alert  (estimated end time - dateFinEstimeeMax)
      - mdi:calendar-clock (postponed - dateFinReport)
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
        """Get end time, whether it's actual, and whether it's postponed.

        Returns: (datetime or None, is_actual: bool, is_postponed: bool)
        """
        outage = self._get_current_interruption()

        if not outage:
            return None, False, False

        # Postponed planned interruption — use dateFinReport
        if outage.get("etat") == "R":
            _, fin_report = self._get_effective_dates(outage)
            if fin_report:
                return fin_report, False, True

        # Actual end time (dateFin)
        date_fin = self._parse_dt(outage.get("dateFin"))
        if date_fin:
            return date_fin, True, False

        # Estimated end time (dateFinEstimeeMax)
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
        """Return icon based on end time type."""
        end_time, is_actual, is_postponed = self._get_end_time_info()
        if end_time is None:
            return "mdi:clock-end"
        if is_postponed:
            return "mdi:calendar-clock"
        if is_actual:
            return "mdi:clock-check"
        return "mdi:clock-alert"


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """Sensor for intervention status — matches HQ ETAPE-PANNE exactly.

    Steps:
      1. Début de la panne (dateDebut)
      2. Évaluation des travaux requis       (codeIntervention = "N")
      3. Équipe désignée                     (codeIntervention = "A" or "R")
      4. Travaux en cours sur le réseau      (codeIntervention = "L", normal)
         Réalisation des travaux par ordre   (codeIntervention = "L", niveauUrgence = "P")
      5. Heure de rétablissement en cours d'évaluation (typeFinPrevue = "U")
         Rétablissement prévu                (typeFinPrevue = "D" or "P")
         Rétablissement graduel              (repriseGraduellePossible = True)
      -> Service rétabli                     (dateFin in past)
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

        # Terminated
        if self._is_outage_terminated(outage):
            return INFO_PANNES_STATES["service_retabli"]

        # GRAP — gradual restoration
        if self.coordinator.data and self.coordinator.data.get(
            "repriseGraduellePossible"
        ):
            return INFO_PANNES_STATES["reprise_graduelle"]

        code = outage.get("codeIntervention")
        niveau = outage.get("niveauUrgence")
        type_fin = outage.get("typeFinPrevue")

        # Step 4 — work in progress
        if code == "L":
            if niveau == "P":
                return INTERVENTION_CODES_MAJEUR["L"]
            return INTERVENTION_CODES.get("L")

        # Steps 2 & 3
        if code in INTERVENTION_CODES:
            return INTERVENTION_CODES[code]

        # Step 5 — restoration estimate (no crew code yet or after work)
        if type_fin:
            return TYPE_FIN_PREVUE_CODES.get(type_fin, f"Inconnu ({type_fin})")

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
    """Sensor for consumption location ID (diagnostic).

    This sensor is visible by default as it shows useful location info.
    """

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


class HydroPannesEtatAPIBrutSensor(HydroPannesSensorBase):
    """Diagnostic sensor exposing raw API state for debugging.

    This sensor is disabled by default.
    """

    _attr_entity_registry_enabled_default = False

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

    This sensor is disabled by default.
    """

    _attr_entity_registry_enabled_default = False

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

        return interruption.get("etat")

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

    This sensor is disabled by default.
    """

    _attr_entity_registry_enabled_default = False

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

        return interruption.get("codeIntervention")

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
            "description_majeur": (
                INTERVENTION_CODES_MAJEUR.get(code)
                if code and interruption.get("niveauUrgence") == "P"
                else None
            ),
            "etat_principal": self._get_main_etat(),
            "etat_interruption": interruption.get("etat"),
            "interruption_planifiee": interruption.get("interruptionPlanifiee"),
        }


class HydroPannesTypeFinPrevueSensor(HydroPannesSensorBase):
    """Sensor for the type of expected end (typeFinPrevue).

    Matches HQ ETAPE-PANNE step 5 labels:
      - "U" -> "Heure de rétablissement en cours d'évaluation"
      - "D" -> "Rétablissement prévu"
      - "P" -> "Rétablissement prévu" (panne majeure — delays not guaranteed)
      - No interruption -> None

    This sensor is disabled by default (diagnostic).
    """

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Type fin prévue"
        self._attr_unique_id = f"{entry.entry_id}_type_fin_prevue"
        self._attr_icon = "mdi:clock-question"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the type of expected end."""
        interruption = self._get_current_interruption()

        if not interruption:
            return None

        code = interruption.get("typeFinPrevue")
        if code is None:
            return None

        return TYPE_FIN_PREVUE_CODES.get(code, f"Inconnu ({code})")

    @property
    def icon(self) -> str:
        """Return icon based on typeFinPrevue value."""
        interruption = self._get_current_interruption()
        if not interruption:
            return "mdi:clock-question"
        code = interruption.get("typeFinPrevue")
        if code == "U":
            return "mdi:clock-remove"
        if code == "D":
            return "mdi:clock-check"
        if code == "P":
            return "mdi:clock-alert"
        return "mdi:clock-question"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional context about the type of expected end."""
        interruption = self._get_current_interruption()

        if not interruption:
            return {}

        code = interruption.get("typeFinPrevue")
        date_fin_estimee = self._parse_dt(interruption.get("dateFinEstimeeMax"))

        return {
            "code_brut": code,
            "date_fin_estimee_max": (
                date_fin_estimee.isoformat() if date_fin_estimee else None
            ),
            "etat_principal": self._get_main_etat(),
            "niveau_urgence": interruption.get("niveauUrgence"),
            "reprise_graduelle": self.coordinator.data.get(
                "repriseGraduellePossible", False
            ) if self.coordinator.data else False,
        }
