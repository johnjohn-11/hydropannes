"""Support for Hydro-Pannes sensors."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.util import dt as dt_util

from .const import (
    CAUSE_CODES,
    CAUSE_DESCRIPTIONS,
    CAUSE_OPTIONS,
    ETAT_PLANIFIE_DECALE,
    ETAT_PLANIFIE_REPORTE,
    INFO_PANNES_OPTIONS,
    INTERVENTION_CODES,
    INTERVENTION_CODES_MAJEUR,
    NIVEAU_URGENCE_CODES,
    NIVEAU_URGENCE_OPTIONS,
    RETABLISSEMENT_DESCRIPTIONS,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR,
    RETABLISSEMENT_OPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR,
    STATUT_INTERVENTION_OPTIONS,
    TYPE_FIN_PREVUE_CODES,
)
from .entity import HydroPannesEntity

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import HydroPannesConfigEntry

_LOGGER = logging.getLogger(__name__)

# The description attribute is fixed text derived from the state, so it is kept out of the recorder.
_UNRECORDED_DESCRIPTION = frozenset({"description"})


def _nb_client_arrondi(nb_client: int) -> str:
    """Return the affected-address count the way the Info-pannes site words it."""
    if nb_client < 500:
        return f"{50 * math.ceil(nb_client / 50)} ou moins"
    if nb_client < 1000:
        return "plus de 500"
    return "plus de 1000"


# Entities are updated by the coordinator; no parallel polling needed.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydroPannesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes sensors for a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            HydroPannesInfoPannesSensor(coordinator, entry),
            HydroPannesNiveauUrgenceSensor(coordinator, entry),
            HydroPannesNombreClientSensor(coordinator, entry),
            HydroPannesDebutSensor(coordinator, entry),
            HydroPannesFinEstimeeSensor(coordinator, entry),
            HydroPannesStatutInterventionSensor(coordinator, entry),
            HydroPannesRetablissementSensor(coordinator, entry),
            HydroPannesCauseSensor(coordinator, entry),
            HydroPannesDureeSensor(coordinator, entry),
            HydroPannesDureeAvantRetablissementSensor(coordinator, entry),
            HydroPannesDerniereMAJSensor(coordinator, entry),
            HydroPannesLieuConsoSensor(coordinator, entry),
        ]
    )


class HydroPannesSensorBase(HydroPannesEntity, SensorEntity):
    """Base class for all Hydro-Pannes sensors."""


class HydroPannesInfoPannesSensor(HydroPannesSensorBase):
    """Sensor reporting the overall service status.

    The state is a language-neutral slug from INFO_PANNES_OPTIONS; the labels shown in the UI come from the translation files. Per-state icons live in icons.json.
    """

    _attr_translation_key = "info_pannes"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = INFO_PANNES_OPTIONS
    _unique_id_suffix = "info_pannes"

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
            if self._is_panne_majeure(active_outage):
                return "panne_majeure"
            return "panne_en_cours"

        planned = self._get_planned_intervention()
        if self._get_terminated_outage() and not self._planned_supersedes_terminated(planned):
            return "service_retabli"

        if planned:
            if self._is_planned_postponed(planned):
                return "interruption_planifiee_reportee"
            if self._is_planned_cancelled(planned):
                return "interruption_planifiee_annulee"
            if self._is_outage_terminated(planned):
                return "interruption_planifiee_terminee"
            if main_etat == "N":
                return "interruption_planifiee_en_cours"
            return "interruption_planifiee_a_venir"

        if main_etat == "A":
            return "aucune_panne"
        if main_etat == "N":
            return "panne_en_cours"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the reason Hydro-Québec gives for a cancelled or postponed planned interruption."""
        if self.native_value not in (
            "interruption_planifiee_annulee",
            "interruption_planifiee_reportee",
        ):
            return {}
        planned = self._get_planned_intervention()
        raison = self._raison_annulation(planned) if planned else None
        return {"raison_annulation": raison} if raison else {}


class HydroPannesNiveauUrgenceSensor(HydroPannesSensorBase):
    """Sensor reporting the urgency level."""

    _attr_translation_key = "niveau_urgence"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = NIVEAU_URGENCE_OPTIONS
    _unique_id_suffix = "niveau_urgence"

    @property
    def native_value(self) -> str | None:
        """Return the urgency level slug, or None if HQ reports none.

        An unrecognized code yields None rather than a made-up state: Home Assistant rejects any value outside _attr_options.
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
    _unique_id_suffix = "nbclient"
    _unrecorded_attributes = frozenset({"arrondi"})

    @property
    def native_value(self) -> int | None:
        """Return the number of affected clients."""
        outage = self._get_current_interruption()
        if not outage:
            return None
        return outage.get("nbClient")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the rounded wording the Info-pannes site shows instead of the exact count."""
        nb_client = self.native_value
        if not isinstance(nb_client, int) or nb_client <= 0:
            return {}
        return {"arrondi": _nb_client_arrondi(nb_client)}


class HydroPannesDebutSensor(HydroPannesSensorBase):
    """Sensor reporting the effective start time."""

    _attr_translation_key = "date_debut"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unique_id_suffix = "date_debut"

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
    _unique_id_suffix = "datefin"

    def _get_end_time_info(self) -> tuple[datetime | None, bool, bool]:
        """Return (end_time, is_actual, is_postponed)."""
        outage = self._get_current_interruption()
        if not outage:
            return None, False, False
        if outage.get("etat") in (ETAT_PLANIFIE_REPORTE, ETAT_PLANIFIE_DECALE):
            _, new_fin = self._get_effective_dates(outage)
            if new_fin:
                return new_fin, False, True
            # No new end date: don't fall through to the abandoned dateFin.
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
    _unique_id_suffix = "statut_intervention"
    _unrecorded_attributes = _UNRECORDED_DESCRIPTION

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
        if self._is_planned_postponed(outage):
            return "interruption_planifiee_reportee"
        if self._is_reprise_graduelle(outage):
            return "reprise_graduelle"
        code = outage.get("codeIntervention")
        type_fin = outage.get("typeFinPrevue")
        if code == "L" and self._is_panne_majeure(outage):
            return INTERVENTION_CODES_MAJEUR["L"]
        if code in INTERVENTION_CODES:
            return INTERVENTION_CODES[code]
        if type_fin:
            return TYPE_FIN_PREVUE_CODES.get(type_fin)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Explain the current step, with the major-outage wording when it applies."""
        statut = self.native_value
        if statut is None:
            return {}
        outage = self._get_current_interruption()
        description = None
        if outage and self._is_panne_majeure(outage):
            description = STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR.get(statut)
        description = description or STATUT_INTERVENTION_DESCRIPTIONS.get(statut)
        return {"description": description} if description else {}


class HydroPannesRetablissementSensor(HydroPannesSensorBase):
    """Sensor reporting the restoration step of an active outage, as the Info-pannes tracker shows it."""

    _attr_translation_key = "retablissement"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = RETABLISSEMENT_OPTIONS
    _unique_id_suffix = "retablissement"
    _unrecorded_attributes = _UNRECORDED_DESCRIPTION

    @property
    def native_value(self) -> str | None:
        """Return the restoration step, or None without an active unplanned outage.

        Mirrors the site's rule. The estimated end is rounded up to the quarter hour before being compared to now. Without an estimate, a crew on the way or on site means the time is being revised. The site also tests a typeFinPrevu field the API never sends (it sends typeFinPrevue), so that test never changes the outcome and is left out.
        """
        outage = self._get_active_outage()
        if not outage:
            return None
        fin_estimee = self._parse_dt(outage.get("dateFinEstimeeMax"))
        if fin_estimee:
            if self._is_date_in_past(self._round_up_quarter(fin_estimee)):
                return "en_revision"
            return "prevu"
        if outage.get("codeIntervention") in ("L", "R"):
            return "en_revision"
        return "en_evaluation"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Explain the restoration step, with the major-outage wording when it applies."""
        etape = self.native_value
        if etape is None:
            return {}
        outage = self._get_active_outage()
        description = None
        if outage and self._is_panne_majeure(outage):
            description = RETABLISSEMENT_DESCRIPTIONS_MAJEUR.get(etape)
        return {"description": description or RETABLISSEMENT_DESCRIPTIONS[etape]}


class HydroPannesCauseSensor(HydroPannesSensorBase):
    """Sensor reporting the cause of the interruption."""

    _attr_translation_key = "cause"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CAUSE_OPTIONS
    _unrecorded_attributes = _UNRECORDED_DESCRIPTION
    _unique_id_suffix = "cause"

    @property
    def native_value(self) -> str | None:
        """Return the cause slug.

        "indeterminee" when Hydro-Québec reports no code or a code outside CAUSE_CODES, as the Info-pannes site does. The raw code is kept in the code_cause attribute either way.
        """
        outage = self._get_current_interruption()
        if not outage:
            return None
        code = outage.get("codeCause")
        if code is None:
            return "indeterminee"
        return CAUSE_CODES.get(str(code), "indeterminee")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw HQ cause code and a description of the cause.

        Several codes map onto a single slug, so the code is kept as an attribute to preserve the distinction the state no longer carries.
        """
        outage = self._get_current_interruption()
        cause = self.native_value
        if not outage or cause is None:
            return {}
        attrs = {"description": CAUSE_DESCRIPTIONS[cause]}
        code = outage.get("codeCause")
        if code is not None:
            attrs["code_cause"] = str(code)
        return attrs


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor reporting the interruption duration in seconds."""

    _attr_translation_key = "duree"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    # No state_class: the value grows with wall-clock time during an outage and
    # resets between outages, so long-term statistics would be a meaningless
    # sawtooth. It remains useful as a live state.
    _unique_id_suffix = "duree"

    @property
    def native_value(self) -> int | None:
        """Return the interruption duration in seconds.

        Uses the effective start/end dates so postponed or rescheduled planned interruptions
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
    _unique_id_suffix = "delai_avant_retablissement"

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
    _unique_id_suffix = "derniere_maj"

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent update timestamp available."""
        interruption = self._get_current_interruption()
        if interruption and interruption.get("datePublication"):
            parsed = self._parse_dt(interruption.get("datePublication"))
            if parsed:
                return parsed
        # Outside an outage there is no datePublication, so fall back to the time of the last successful poll.
        return self.coordinator.last_success_time


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Diagnostic sensor reporting the consumption location ID."""

    _attr_translation_key = "lieu_consommation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unique_id_suffix = "idlieuconso"

    @property
    def native_value(self) -> str | None:
        """Return the consumption location ID."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("idLieuConso")
