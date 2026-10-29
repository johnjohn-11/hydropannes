"""Binary sensors for Hydro-Pannes.

Provides two binary sensors per configured location:

- **État du service** (BinarySensorDeviceClass.PROBLEM): ``True`` when an active unplanned outage or active planned intervention is in progress.
- **Intervention planifiée** (no device class): ``True`` when at least one non-terminated planned intervention exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.util import dt as dt_util
from pyhydropannes import parse_datetime
from pyhydropannes.const import (
    GRADUAL_RESTORATION_END_MARGIN,
    GRADUAL_RESTORATION_PLANNED_MINUTES,
    ROOT_OFF,
)

from .entity import HydroPannesEntity

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from pyhydropannes import Interruption

    from . import HydroPannesConfigEntry

PARALLEL_UPDATES = 0

# The service-status binary sensor exposes no extra attributes — its on/off state is the whole signal. The report-window and planned-intervention fields below live only on the planned-intervention binary sensor. Fields already on a dedicated sensor, or carried by the hydropannes_data_changed event (etat, codeMunicipal, codeRemarque, probabilite), are not duplicated as attributes.
INTERVENTION_PLANIFIEE_ATTRIBUTE_KEYS = (
    "dateDebutReport",
    "dateFinReport",
    "dateDebutDecalage",
    "dateFinDecalage",
    "dureePrevu",
    "interruptionPlanifiee",
)


def _iso(value: datetime | None) -> str | None:
    return dt_util.as_local(value).isoformat() if value else None


def _interruption_attributes(intr: Interruption, keys: tuple[str, ...]) -> dict[str, Any]:
    """Return the given raw interruption fields, dates as local ISO strings and None values left out."""
    attrs: dict[str, Any] = {}
    for key in keys:
        val = intr.raw.get(key)
        if val is None:
            continue
        if key.startswith("date") and val:
            attrs[key] = _iso(parse_datetime(val)) or val
        else:
            attrs[key] = val
    return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydroPannesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes binary sensors for a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            HydroPannesEtatServiceBinarySensor(coordinator, entry),
            HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry),
        ]
    )


class HydroPannesBinarySensorBase(HydroPannesEntity, BinarySensorEntity):
    """Base class for all Hydro-Pannes binary sensors."""


class HydroPannesEtatServiceBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether there is an active service problem.

    ``True`` when the root etat is "N" (active outage or planned interruption in progress) or an unplanned interruption is under way, ``False`` otherwise, ``None`` before the first fetch.
    """

    _attr_translation_key = "etat_service"
    _write_after_details = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _unique_id_suffix = "etat_service"

    @property
    def is_on(self) -> bool | None:
        """Return True when power is out or a planned interruption is actively in progress."""
        if not self.coordinator.data:
            return None
        # "N" means the service point is not fed, whether or not an interruption object can be matched to it. An unplanned interruption under way also counts, as the site shows it as an outage even while the root etat still says "A".
        return self._etat.status == ROOT_OFF or self._etat.active_outage is not None


class HydroPannesInterventionPlanifieeBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether a planned intervention exists.

    Returns ``True`` when at least one planned interruption that is neither cancelled nor terminated is present in the API response (active or upcoming).
    """

    # No device class: RUNNING would read "Running" while the intervention is only upcoming. The on/off labels come from the translations.
    _attr_translation_key = "intervention_planifiee"
    _write_after_details = True
    _unique_id_suffix = "intervention_planifiee"

    @property
    def is_on(self) -> bool | None:
        """Return True if a planned intervention that is neither cancelled nor terminated exists."""
        if not self.coordinator.data:
            return None
        return bool(self._etat.pending_planned)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the first planned interruption that is neither cancelled nor terminated."""
        pending = self._etat.pending_planned
        if not pending:
            return {}
        attrs = _interruption_attributes(pending[0], INTERVENTION_PLANIFIEE_ATTRIBUTE_KEYS)
        attrs.update(self._resume(pending[0]))
        if len(pending) > 1:
            attrs["interruptions_suivantes"] = [self._resume(i) for i in pending[1:]]
        return attrs

    def _resume(self, intr: Interruption) -> dict[str, Any]:
        """Summarize a planned interruption the way the site's planned-interruption card shows it."""
        fin = intr.effective_end
        duree = intr.planned_duration_minutes
        item: dict[str, Any] = {
            "debut": _iso(intr.effective_start),
            "fin": _iso(fin),
            "duree_prevue": duree,
        }
        # From 480 minutes of planned work the site warns about a gradual restoration and shows the end as a window up to 5 hours later.
        if duree is not None and duree >= GRADUAL_RESTORATION_PLANNED_MINUTES:
            item["reprise_graduelle_possible"] = True
            if fin:
                item["fin_au_plus_tard"] = _iso(fin + GRADUAL_RESTORATION_END_MARGIN)
        # On an interruption not yet postponed, the report dates are the fallback slot the site lists under "En cas de report".
        if not intr.is_postponed and intr.postponed_start:
            item["report_debut"] = _iso(intr.postponed_start)
            item["report_fin"] = _iso(intr.postponed_end)
        return item
