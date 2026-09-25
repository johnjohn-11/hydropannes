"""Base entity shared by every Hydro-Pannes sensor and binary sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from . import HydroPannesConfigEntry


class HydroPannesEntity(
    HydroPannesHelperMixin, CoordinatorEntity[HydroPannesDataUpdateCoordinator]
):
    """Wire an entity to its location's coordinator and device.

    Subclasses set ``_unique_id_suffix``. The suffixes predate this class and some differ from the translation key (``nbclient``, ``datefin``...): changing one would orphan the entity in the registry.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _unique_id_suffix: str

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: HydroPannesConfigEntry,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._unique_id_suffix}"
        # The device is named after the location alone: Home Assistant already shows the integration name around it, and with has_entity_name the device name prefixes every entity name.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hydro-Québec",
            model="Info-pannes",
        )

    @property
    def available(self) -> bool:
        """Return True only when the coordinator has successfully fetched data."""
        return super().available and self.coordinator.data is not None
