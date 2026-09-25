"""Binary sensors for Hydro-Pannes.

Provides three binary sensors per configured location:

- **État du service** (BinarySensorDeviceClass.PROBLEM): ``True`` when an
  active unplanned outage or active planned intervention is in progress.
- **Intervention planifiée** (BinarySensorDeviceClass.RUNNING): ``True``
  when at least one non-terminated planned intervention exists.
- **Compatibilité API** (EntityCategory.DIAGNOSTIC, BinarySensorDeviceClass.PROBLEM):
  ``True`` when the Hydro-Québec API response no longer contains the expected
  root-level fields, indicating a breaking schema change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .const import GRAP_DUREE_PREVUE_MINUTES
from .entity import HydroPannesEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import HydroPannesConfigEntry

# Entities are updated by the coordinator; no parallel polling needed.
PARALLEL_UPDATES = 0

# The service-status binary sensor exposes no extra attributes — its on/off
# state is the whole signal. The report-window and planned-intervention fields
# below live only on the planned-intervention binary sensor. Fields already on
# a dedicated sensor, or carried by the hydropannes_data_changed event (etat,
# codeMunicipal, codeRemarque, probabilite), are not duplicated as attributes.
INTERVENTION_PLANIFIEE_ATTRIBUTE_KEYS = (
    "dateDebutReport",
    "dateFinReport",
    "dateDebutDecalage",
    "dateFinDecalage",
    "dureePrevu",
    "interruptionPlanifiee",
)


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
            HydroPannesAPICompatibilityBinarySensor(coordinator, entry),
        ]
    )


class HydroPannesBinarySensorBase(HydroPannesEntity, BinarySensorEntity):
    """Base class for all Hydro-Pannes binary sensors."""


class HydroPannesEtatServiceBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether there is an active service problem.

    ``True`` when the root etat is "N" (active outage or planned interruption in progress), ``False`` otherwise, ``None`` before the first fetch.
    """

    _attr_translation_key = "etat_service"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _unique_id_suffix = "etat_service"

    @property
    def is_on(self) -> bool | None:
        """Return True when power is out or a planned interruption is actively in progress."""
        if not self.coordinator.data:
            return None
        # The root etat alone decides: "N" means the service point is not fed, whether or not an interruption object can be matched to it.
        return self._get_main_etat() == "N"


class HydroPannesInterventionPlanifieeBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether a planned intervention exists.

    Returns ``True`` when at least one planned interruption that is neither cancelled nor terminated is
    present in the API response (active or upcoming).
    """

    _attr_translation_key = "intervention_planifiee"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _unique_id_suffix = "intervention_planifiee"

    @property
    def is_on(self) -> bool | None:
        """Return True if a planned intervention that is neither cancelled nor terminated exists."""
        if not self.coordinator.data:
            return None
        return bool(self._get_pending_planned())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the first planned interruption that is neither cancelled nor terminated."""
        pending = self._get_pending_planned()
        if not pending:
            return {}
        attrs = self._interruption_attributes(pending[0], INTERVENTION_PLANIFIEE_ATTRIBUTE_KEYS)
        if len(pending) > 1:
            attrs["interruptions_suivantes"] = [self._suivante(i) for i in pending[1:]]
        return attrs

    def _suivante(self, intr: dict[str, Any]) -> dict[str, Any]:
        """Summarize one of the other upcoming planned interruptions, as the site lists them."""
        debut, fin = self._get_effective_dates(intr)
        duree = intr.get("dureePrevu")
        item: dict[str, Any] = {
            "debut": debut.isoformat() if debut else None,
            "fin": fin.isoformat() if fin else None,
            "duree_prevue": duree,
        }
        # The site warns about a possible gradual restoration from 480 minutes of planned work.
        if isinstance(duree, int | float) and duree >= GRAP_DUREE_PREVUE_MINUTES:
            item["reprise_graduelle_possible"] = True
        return item


class HydroPannesAPICompatibilityBinarySensor(HydroPannesBinarySensorBase):
    """Diagnostic sensor monitoring the Hydro-Québec API response structure.

    Returns ``True`` (Problem) when the coordinator has detected that the API
    response is missing one or more expected root-level fields, which indicates
    a breaking schema change that requires an integration update.

    This sensor is in the DIAGNOSTIC category and is hidden from the default
    dashboard view; it is intended for troubleshooting and automations.
    """

    _attr_translation_key = "api_compatibilite"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _unique_id_suffix = "api_compatibility"

    @property
    def available(self) -> bool:
        """Stay available even when the last update failed.

        This sensor reports coordinator state rather than payload data. A payload the integration cannot parse fails the update, and that is precisely when the user needs this sensor to read "problem" instead of going unavailable along with every other entity.
        """
        return True

    @property
    def is_on(self) -> bool:
        """Return True (Problem) when the API structure is incompatible."""
        return not self.coordinator.api_compatible
