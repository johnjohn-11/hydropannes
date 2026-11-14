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
from pyhydropannes import EndKind

from .const import (
    CAUSE_DESCRIPTIONS,
    CAUSE_DESCRIPTIONS_EN,
    CAUSE_OPTIONS,
    CAUSE_SLUGS,
    INFO_PANNES_OPTIONS,
    INFO_PANNES_SLUGS,
    NIVEAU_URGENCE_OPTIONS,
    NIVEAU_URGENCE_SLUGS,
    RAISON_ANNULATION,
    RETABLISSEMENT_DESCRIPTIONS,
    RETABLISSEMENT_DESCRIPTIONS_EN,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR_EN,
    RETABLISSEMENT_OPTIONS,
    RETABLISSEMENT_SLUGS,
    STATUT_INTERVENTION_DESCRIPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS_EN,
    STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR,
    STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR_EN,
    STATUT_INTERVENTION_OPTIONS,
    STATUT_INTERVENTION_SLUGS,
)
from .entity import HydroPannesEntity

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import HydroPannesConfigEntry


# The description attribute is fixed text derived from the state, so it is kept out of the recorder.
_UNRECORDED_DESCRIPTION = frozenset({"description"})

_END_ICONS = {
    EndKind.POSTPONED: "mdi:calendar-clock",
    EndKind.ACTUAL: "mdi:clock-check",
    EndKind.ESTIMATED: "mdi:clock-alert",
}


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
        if self.coordinator.data is None:
            return None
        status = self._etat.service_status
        return INFO_PANNES_SLUGS[status] if status else None

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
        if not interruption or not interruption.urgency:
            return None
        return NIVEAU_URGENCE_SLUGS[interruption.urgency]


class HydroPannesAdressesToucheesSensor(HydroPannesSensorBase):
    """Sensor reporting the number of affected addresses."""

    _attr_translation_key = "adresses_touchees"
    # The unit comes from the translations. Kept "clients" in every language: a different unit would split the long-term statistics.
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

    @property
    def native_value(self) -> datetime | None:
        """Return the effective end time."""
        outage = self._etat.current
        return outage.display_end if outage else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the earliest estimated end when Hydro-Québec gives a range, as the site shows "between" the two."""
        outage = self._etat.current
        fin_min = outage.estimated_end_earliest if outage else None
        return {"fin_estimee_min": dt_util.as_local(fin_min).isoformat()} if fin_min else {}

    @property
    def icon(self) -> str:
        """Return an icon reflecting the type of end time."""
        outage = self._etat.current
        kind = outage.end_kind if outage and outage.display_end else None
        return _END_ICONS[kind] if kind else "mdi:clock-end"


class HydroPannesStatutInterventionSensor(HydroPannesSensorBase):
    """Sensor reporting the current intervention step."""

    _attr_translation_key = "statut_intervention"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUT_INTERVENTION_OPTIONS
    _unique_id_suffix = "statut_intervention"
    _unrecorded_attributes = _UNRECORDED_DESCRIPTION

    @property
    def native_value(self) -> str | None:
        """Return the current intervention step slug, None when the site shows no step."""
        step = self._etat.intervention_step
        return STATUT_INTERVENTION_SLUGS[step] if step else None

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
        """Return the restoration step of the site's tracker, None without an interruption under way."""
        step = self._etat.restoration_step
        return RETABLISSEMENT_SLUGS[step] if step else None

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

        "indeterminee" when Hydro-Québec reports no code or one the Info-pannes site does not map. The raw code is kept in the code_cause attribute either way.
        """
        outage = self._etat.current
        return CAUSE_SLUGS[outage.cause] if outage else None

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
        elapsed = outage.elapsed(dt_util.utcnow()) if outage else None
        return round(elapsed.total_seconds()) if elapsed is not None else None


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
        remaining = self._etat.time_to_restoration
        return round(remaining.total_seconds()) if remaining is not None else None


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
