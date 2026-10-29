"""Support for Hydro-Pannes sensors."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.util import dt as dt_util
from pyhydropannes import round_up_quarter
from pyhydropannes.const import PLANNED_POSTPONED, PLANNED_SHIFTED, ROOT_OFF, ROOT_ON

from .const import (
    CAUSE_CODES,
    CAUSE_DESCRIPTIONS,
    CAUSE_DESCRIPTIONS_EN,
    CAUSE_OPTIONS,
    INFO_PANNES_OPTIONS,
    INTERVENTION_CODES,
    INTERVENTION_CODES_MAJEUR,
    NIVEAU_URGENCE_CODES,
    NIVEAU_URGENCE_OPTIONS,
    RAISON_ANNULATION,
    RETABLISSEMENT_DESCRIPTIONS,
    RETABLISSEMENT_DESCRIPTIONS_EN,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR_EN,
    RETABLISSEMENT_OPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS_EN,
    STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR,
    STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR_EN,
    STATUT_INTERVENTION_OPTIONS,
    TYPE_FIN_PREVUE_CODES,
)
from .entity import HydroPannesEntity

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import HydroPannesConfigEntry


# The description attribute is fixed text derived from the state, so it is kept out of the recorder.
_UNRECORDED_DESCRIPTION = frozenset({"description"})


def _nb_client_arrondi(nb_client: int, *, english: bool = False) -> str:
    """Return the affected-address count the way the Info-pannes site words it, in French or in the site's English."""
    if nb_client < 500:
        n = 50 * math.ceil(nb_client / 50)
        return f"{n} or less" if english else f"{n} ou moins"
    if nb_client < 1000:
        return "Over 500" if english else "plus de 500"
    return "Over 1000" if english else "plus de 1000"


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
            HydroPannesAdressesToucheesSensor(coordinator, entry),
            HydroPannesDateDebutSensor(coordinator, entry),
            HydroPannesDateFinSensor(coordinator, entry),
            HydroPannesStatutInterventionSensor(coordinator, entry),
            HydroPannesRetablissementSensor(coordinator, entry),
            HydroPannesCauseSensor(coordinator, entry),
            HydroPannesDureeSensor(coordinator, entry),
            HydroPannesDelaiAvantRetablissementSensor(coordinator, entry),
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
    _write_after_details = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = INFO_PANNES_OPTIONS
    _unique_id_suffix = "info_pannes"

    @property
    def native_value(self) -> str | None:
        """Return the service status string."""
        if not self.coordinator.data:
            return None

        root_etat = self._etat.status
        interruptions = self._etat.interruptions
        now = dt_util.utcnow()

        if not interruptions:
            if root_etat == ROOT_ON:
                return "aucune_panne"
            if root_etat == ROOT_OFF:
                return "panne_en_cours"
            return None

        if self._etat.out_of_sync:
            return "panne_en_cours"

        active_outage = self._etat.active_outage
        if active_outage and self._etat.is_gradual_restoration(active_outage):
            return "reprise_graduelle"

        if active_outage:
            if active_outage.is_major:
                return "panne_majeure"
            return "panne_en_cours"

        planned = self._etat.planned
        if self._etat.terminated_outage and not (planned and planned.supersedes_terminated(now)):
            return "service_retabli"

        if planned:
            if planned.is_postponed:
                return "interruption_planifiee_reportee"
            if planned.is_cancelled:
                return "interruption_planifiee_annulee"
            if planned.is_terminated(now):
                return "interruption_planifiee_terminee"
            if root_etat == ROOT_OFF:
                return "interruption_planifiee_en_cours"
            return "interruption_planifiee_a_venir"

        if root_etat == ROOT_ON:
            return "aucune_panne"
        if root_etat == ROOT_OFF:
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
        planned = self._etat.planned
        raison = RAISON_ANNULATION.get(planned.cancellation_reason or "") if planned else None
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
        interruption = self._etat.current
        if not interruption:
            return None
        niveau = interruption.urgency_code
        if not niveau:
            return None
        return NIVEAU_URGENCE_CODES.get(niveau)


class HydroPannesAdressesToucheesSensor(HydroPannesSensorBase):
    """Sensor reporting the number of affected addresses."""

    _attr_translation_key = "adresses_touchees"
    _attr_native_unit_of_measurement = "clients"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unique_id_suffix = "nbclient"
    _unrecorded_attributes = frozenset({"arrondi"})

    @property
    def native_value(self) -> int | None:
        """Return the number of affected clients."""
        outage = self._etat.current
        if not outage:
            return None
        return outage.customers

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the rounded wording the Info-pannes site shows instead of the exact count."""
        nb_client = self.native_value
        if not isinstance(nb_client, int) or nb_client <= 0:
            return {}
        return {"arrondi": _nb_client_arrondi(nb_client, english=self._english)}


class HydroPannesDateDebutSensor(HydroPannesSensorBase):
    """Sensor reporting the effective start time."""

    _attr_translation_key = "date_debut"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unique_id_suffix = "date_debut"

    @property
    def native_value(self) -> datetime | None:
        """Return the effective start time."""
        outage = self._etat.current
        if not outage:
            return None
        return outage.effective_start


class HydroPannesDateFinSensor(HydroPannesSensorBase):
    """Sensor reporting the effective end time."""

    _attr_translation_key = "date_fin"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unique_id_suffix = "datefin"

    def _get_end_time_info(self) -> tuple[datetime | None, bool, bool]:
        """Return (end_time, is_actual, is_postponed)."""
        outage = self._etat.current
        if not outage:
            return None, False, False
        if outage.status in (PLANNED_POSTPONED, PLANNED_SHIFTED):
            new_fin = outage.effective_end
            if new_fin:
                return new_fin, False, True
            # No new end date: don't fall through to the abandoned dateFin.
            return None, False, True
        date_fin = outage.end
        if date_fin:
            return date_fin, True, False
        date_fin_estimee = outage.estimated_end_max
        if date_fin_estimee:
            return date_fin_estimee, False, False
        return None, False, False

    @property
    def native_value(self) -> datetime | None:
        """Return the effective end time."""
        end_time, _, _ = self._get_end_time_info()
        return end_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the earliest estimated end when Hydro-Québec gives a range, as the site shows "between" the two."""
        end_time, is_actual, is_postponed = self._get_end_time_info()
        outage = self._etat.current
        if end_time is None or is_actual or is_postponed or not outage:
            return {}
        fin_min = outage.estimated_end_min
        if fin_min and fin_min < end_time:
            return {"fin_estimee_min": dt_util.as_local(fin_min).isoformat()}
        return {}

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
        outage = self._etat.current
        if not outage:
            return None
        planned = outage.planned
        # Checked before termination: the site shows a cancelled planned interruption as cancelled even once its slot is past.
        if planned and outage.is_cancelled:
            return "interruption_planifiee_annulee"
        if outage.is_terminated(dt_util.utcnow()):
            return "service_retabli"
        if outage.is_postponed:
            return "interruption_planifiee_reportee"
        if self._etat.is_gradual_restoration(outage):
            return "reprise_graduelle"
        if self._etat.is_planned_in_progress(outage):
            # The site's planned-interruption tracker shows restoration as the current step once an end is known.
            return "retablissement_prevu" if outage.effective_end else "travaux_en_cours"
        if planned:
            # Planned but not under way (root etat not "N"), as the info-pannes sensor reports it. The site shows no step for it.
            return "interruption_planifiee_a_venir"
        code = outage.intervention_code
        type_fin = outage.end_type_code
        if code == "L" and outage.is_major:
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
        outage = self._etat.current
        description = None
        if outage and outage.is_major:
            majeur = (
                STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR_EN
                if self._english
                else STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR
            )
            description = majeur.get(statut)
        normal = (
            STATUT_INTERVENTION_DESCRIPTIONS_EN
            if self._english
            else STATUT_INTERVENTION_DESCRIPTIONS
        )
        description = description or normal.get(statut)
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
        if self._etat.out_of_sync:
            return None
        outage = self._etat.active_outage
        if not outage:
            planned = self._etat.planned
            if planned and self._etat.is_planned_in_progress(planned):
                # A planned interruption has a known end: the site shows it as expected, without revision.
                return "prevu" if planned.effective_end else None
            return None
        fin_estimee = outage.estimated_end_max
        if fin_estimee:
            # Rounded in local time, as the site does: a quarter hour is not the same in every offset.
            if round_up_quarter(dt_util.as_local(fin_estimee)) <= dt_util.now():
                return "en_revision"
            return "prevu"
        if outage.intervention_code in ("L", "R"):
            return "en_revision"
        return "en_evaluation"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Explain the restoration step, with the major-outage wording when it applies."""
        etape = self.native_value
        if etape is None:
            return {}
        outage = self._etat.active_outage
        description = None
        if outage and outage.is_major:
            majeur = (
                RETABLISSEMENT_DESCRIPTIONS_MAJEUR_EN
                if self._english
                else RETABLISSEMENT_DESCRIPTIONS_MAJEUR
            )
            description = majeur.get(etape)
        normal = RETABLISSEMENT_DESCRIPTIONS_EN if self._english else RETABLISSEMENT_DESCRIPTIONS
        return {"description": description or normal[etape]}


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
        outage = self._etat.current
        if not outage:
            return None
        code = outage.cause_code
        if code is None:
            return "indeterminee"
        return CAUSE_CODES.get(code, "indeterminee")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw HQ cause code and a description of the cause.

        Several codes map onto a single slug, so the code is kept as an attribute to preserve the distinction the state no longer carries.
        """
        outage = self._etat.current
        cause = self.native_value
        if not outage or cause is None:
            return {}
        descriptions = CAUSE_DESCRIPTIONS_EN if self._english else CAUSE_DESCRIPTIONS
        attrs = {"description": descriptions[cause]}
        if outage.cause_code is not None:
            attrs["code_cause"] = outage.cause_code
        return attrs


class HydroPannesDureeSensor(HydroPannesSensorBase):
    """Sensor reporting the interruption duration in seconds."""

    _attr_translation_key = "duree"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    # No state_class: the value grows with wall-clock time during an outage and resets between outages, so long-term statistics would be a meaningless sawtooth. It remains useful as a live state.
    _unique_id_suffix = "duree"

    @property
    def native_value(self) -> int | None:
        """Return the interruption duration in seconds.

        Uses the effective start/end dates so postponed or rescheduled planned interruptions are measured against their real (rescheduled) window rather than the cancelled original slot. Returns None when the interruption has not started yet (e.g. an upcoming planned intervention), which avoids reporting a negative duration. When the interruption is ongoing (no effective end date), the elapsed time up to now is returned.
        """
        outage = self._etat.current
        if not outage:
            return None
        effective_debut, effective_fin = outage.effective_start, outage.effective_end
        now = dt_util.utcnow()
        if not effective_debut or effective_debut > now:
            return None
        end = effective_fin or now
        return max(round((end - effective_debut).total_seconds()), 0)


class HydroPannesDelaiAvantRetablissementSensor(HydroPannesSensorBase):
    """Sensor reporting time remaining until restoration in seconds."""

    _attr_translation_key = "delai_avant_retablissement"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    # No state_class: this countdown shifts every poll and resets between outages, so long-term statistics would be a meaningless sawtooth.
    _unique_id_suffix = "delai_avant_retablissement"

    @property
    def native_value(self) -> int | None:
        """Return seconds until estimated restoration, or None."""
        outage = self._etat.current
        if not outage or outage.is_terminated(dt_util.utcnow()) or not self._etat.is_active(outage):
            return None
        date_fin_estimee = outage.estimated_end_max
        if not date_fin_estimee:
            return None
        remaining = (date_fin_estimee - dt_util.now()).total_seconds()
        return round(remaining) if remaining >= 0 else None


class HydroPannesDerniereMAJSensor(HydroPannesSensorBase):
    """Sensor reporting the last update time."""

    _attr_translation_key = "derniere_maj"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # Outside an outage the state is the poll time, which changes every few minutes and fills the recorder.
    _attr_entity_registry_enabled_default = False
    _unique_id_suffix = "derniere_maj"

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent update timestamp available."""
        interruption = self._etat.current
        if interruption and interruption.published:
            return interruption.published
        # Outside an outage there is no datePublication, so fall back to the time of the last successful poll.
        return self.coordinator.last_success_time


class HydroPannesLieuConsoSensor(HydroPannesSensorBase):
    """Diagnostic sensor reporting the consumption location number, to tell locations apart in logs and on the event bus."""

    _attr_translation_key = "lieu_consommation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _unique_id_suffix = "idlieuconso"

    @property
    def native_value(self) -> str | None:
        """Return the consumption location number."""
        return self._etat.location_id
