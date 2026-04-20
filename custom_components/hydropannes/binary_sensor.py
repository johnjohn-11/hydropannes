"""Support for Hydro-Pannes binary sensors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes binary sensors."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.title

    entities = [
        HydroPannesEtatServiceBinarySensor(coordinator, entry, nom_lieu),
        HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry, nom_lieu),
        HydroPannesAPICompatibilityBinarySensor(coordinator, entry, nom_lieu),
    ]

    async_add_entities(entities)


class HydroPannesBinarySensorBase(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    BinarySensorEntity,
    HydroPannesHelperMixin,
):
    """Base class for Hydro-Pannes binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Hydro-Pannes {nom_lieu}",
            "manufacturer": "Hydro-Québec (Custom)",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "lieu_consommation": self.coordinator.lieu_conso,
            "nom_lieu": self._nom_lieu,
        }


class HydroPannesEtatServiceBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor for the overall service status (Power Outage)."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "État du service"
        self._attr_unique_id = f"{entry.entry_id}_service_status"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        """Return True if an active (non-planned) outage is detected."""
        if not self.coordinator.data:
            return None
        return self._get_active_outage() is not None

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        return "mdi:power-plug-off" if self.is_on else "mdi:power-plug"


class HydroPannesInterventionPlanifieeBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor for planned maintenance (AIP)."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Intervention planifiée"
        self._attr_unique_id = f"{entry.entry_id}_planned_intervention"
        self._attr_device_class = BinarySensorDeviceClass.UPDATE

    @property
    def is_on(self) -> bool | None:
        """Return True if a planned intervention is detected."""
        if not self.coordinator.data:
            return None
        return self._get_planned_intervention() is not None

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        return "mdi:calendar-clock" if self.is_on else "mdi:calendar-check"


class HydroPannesAPICompatibilityBinarySensor(HydroPannesBinarySensorBase):
    """Diagnostic binary sensor to monitor API structure changes."""

    def __init__(self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Compatibilité API"
        self._attr_unique_id = f"{entry.entry_id}_api_compatibility"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return True (Problem) if the API structure is incompatible."""
        return not self.coordinator.api_compatible

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        return "mdi:api-off" if self.is_on else "mdi:api"
