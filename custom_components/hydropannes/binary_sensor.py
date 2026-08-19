"""Binary sensors for Hydro-Pannes.

Provides three binary sensors per configured location:

- **État du service** (BinarySensorDeviceClass.PROBLEM): ``True`` when an
  active unplanned outage or active planned intervention (AIP) is in progress.
- **Intervention planifiée** (BinarySensorDeviceClass.RUNNING): ``True``
  when at least one non-terminated planned intervention exists.
- **Compatibilité API** (EntityCategory.DIAGNOSTIC, BinarySensorDeviceClass.PROBLEM):
  ``True`` when the Hydro-Québec API response no longer contains the expected
  root-level fields, indicating a breaking schema change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import HydroPannesConfigEntry

_LOGGER = logging.getLogger(__name__)

# Entities are updated by the coordinator; no parallel polling needed.
PARALLEL_UPDATES = 0

# Interruption fields surfaced as extra state attributes. Date fields are
# formatted consistently (localized ISO) by _interruption_attributes, matching
# the info-pannes sensor.
ETAT_SERVICE_ATTRIBUTE_KEYS = (
    "dateDebut",
    "dateFin",
    "dateDebutReport",
    "dateFinReport",
    "dateFinEstimeeMax",
    "etat",
    "interruptionPlanifiee",
    "codeIntervention",
    "niveauUrgence",
    "nbClient",
    "codeCause",
    "codeMunicipal",
    "dureePrevu",
    "typeFinPrevue",
)

# The planned-intervention sensor exposes the same fields plus AIP-specific
# metadata (publication date, remark code, probability).
INTERVENTION_PLANIFIEE_ATTRIBUTE_KEYS = (
    *ETAT_SERVICE_ATTRIBUTE_KEYS,
    "datePublication",
    "codeRemarque",
    "probabilite",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydroPannesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes binary sensors for a config entry."""
    coordinator = entry.runtime_data
    nom_lieu = entry.title

    async_add_entities(
        [
            HydroPannesEtatServiceBinarySensor(coordinator, entry, nom_lieu),
            HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry, nom_lieu),
            HydroPannesAPICompatibilityBinarySensor(coordinator, entry, nom_lieu),
        ]
    )


class HydroPannesBinarySensorBase(
    HydroPannesHelperMixin,
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Base class shared by all Hydro-Pannes binary sensors.

    Wires up the coordinator, device info, and the availability guard that
    prevents entities from reporting stale state when no data has been fetched.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
        # Device identity is fixed for the entity's lifetime; set it once here
        # rather than rebuilding a DeviceInfo on every property access.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"HydroPannes {nom_lieu}",
            manufacturer="Hydro-Québec",
            model="Info-pannes",
        )

    @property
    def available(self) -> bool:
        """Return True only after a successful data fetch."""
        return super().available and self.coordinator.data is not None


class HydroPannesEtatServiceBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether there is an active service problem.

    Maps to the BinarySensorDeviceClass.PROBLEM convention:
    - ``True``  → problem detected (active outage or active AIP).
    - ``False`` → service is normal (root etat != "N").
    - ``None``  → state is unknown (no data yet).

    Note: when ``etat == "N"`` but no specific interruption can be matched,
    the sensor still returns ``True`` because the API confirms power is out,
    even if the interruption object cannot be resolved.
    """

    _attr_translation_key = "etat_service"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_etat_service"

    @property
    def is_on(self) -> bool | None:
        """Return True when power is out or an AIP is actively in progress."""
        if not self.coordinator.data:
            return None

        main_etat = self._get_main_etat()

        # Root etat != "N" means the service point is fed normally.
        if main_etat != "N":
            return False

        # Active unplanned outage.
        if self._get_active_outage():
            return True

        # Active planned intervention (AIP currently in progress).
        planned = self._get_planned_intervention()
        if planned and self._is_outage_active(planned):
            return True

        # etat is "N" (power out) but no specific interruption matched.
        # The API confirms there is a problem, even without a resolved outage.
        return True

    @property
    def icon(self) -> str:
        """Return an icon reflecting the current service state."""
        return "mdi:power-plug-off" if self.is_on else "mdi:power-plug"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the most relevant active interruption."""
        if not self.coordinator.data:
            return {}
        interruptions = self._get_interruptions()
        if not interruptions:
            return {}

        # Select the best interruption in priority order.
        active_interruption = self._get_active_outage()
        if not active_interruption:
            active_interruption = self._get_planned_intervention()
        if not active_interruption:
            active_interruption = interruptions[0]

        return self._interruption_attributes(active_interruption, ETAT_SERVICE_ATTRIBUTE_KEYS)


class HydroPannesInterventionPlanifieeBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether a planned intervention (AIP) exists.

    Returns ``True`` when at least one non-terminated planned interruption is
    present in the API response (active or upcoming).
    """

    _attr_translation_key = "intervention_planifiee"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_intervention_planifiee"

    @property
    def is_on(self) -> bool | None:
        """Return True if a non-terminated planned intervention exists."""
        if not self.coordinator.data:
            return None
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr) and not self._is_outage_terminated(intr):
                return True
        return False

    @property
    def icon(self) -> str:
        """Return an icon reflecting whether an AIP is pending or done."""
        return "mdi:calendar-clock" if self.is_on else "mdi:calendar-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the most relevant non-terminated AIP."""
        if not self.coordinator.data:
            return {}
        interruptions = self._get_interruptions()
        if not interruptions:
            return {}

        planned = next(
            (
                i
                for i in interruptions
                if self._is_planned_intervention(i) and not self._is_outage_terminated(i)
            ),
            None,
        )
        if not planned:
            return {}

        return self._interruption_attributes(planned, INTERVENTION_PLANIFIEE_ATTRIBUTE_KEYS)


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

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_unique_id = f"{entry.entry_id}_api_compatibility"

    @property
    def is_on(self) -> bool:
        """Return True (Problem) when the API structure is incompatible."""
        return not self.coordinator.api_compatible

    @property
    def icon(self) -> str:
        """Return an icon reflecting the API compatibility state."""
        return "mdi:api-off" if self.is_on else "mdi:api"
