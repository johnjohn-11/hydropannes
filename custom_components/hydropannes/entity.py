"""Base entity shared by every Hydro-Pannes sensor and binary sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator

if TYPE_CHECKING:
    from asyncio import Handle

    from . import HydroPannesConfigEntry
    from .model import EtatLieu


class HydroPannesEntity(CoordinatorEntity[HydroPannesDataUpdateCoordinator]):
    """Wire an entity to its location's coordinator and device.

    Subclasses set ``_unique_id_suffix``. The suffixes predate this class and some differ from the translation key (``nbclient``, ``datefin``...): changing one would orphan the entity in the registry.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _unique_id_suffix: str
    # Set on the entities automations trigger on (Info-pannes, État du service, Intervention planifiée, the calendar), so an automation they start finds the detail sensors of the same poll already written.
    _write_after_details = False
    _deferred_write: Handle | None = None

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

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write the state, after the other entities of the poll for a summary entity.

        The coordinator calls every listener in turn within one loop iteration, so a write scheduled with call_soon runs once all of them have written, whatever order Home Assistant added the entities in.
        """
        if not self._write_after_details:
            super()._handle_coordinator_update()
            return
        if self._deferred_write is None:
            self._deferred_write = self.hass.loop.call_soon(self._write_deferred)

    @callback
    def _write_deferred(self) -> None:
        self._deferred_write = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Drop a write still scheduled for an entity being removed."""
        if self._deferred_write is not None:
            self._deferred_write.cancel()
            self._deferred_write = None
        await super().async_will_remove_from_hass()

    @property
    def _etat(self) -> EtatLieu:
        """Return the reading of the last successful payload, computed once per poll by the coordinator."""
        return self.coordinator.etat

    @property
    def _english(self) -> bool:
        """Return True when attribute texts should be in English.

        Home Assistant translates states and names but not attribute values, so the integration picks the French or English text itself from the configured language. French by default, also when the entity is not attached to Home Assistant.
        """
        hass = getattr(self, "hass", None)
        return hass is not None and not (hass.config.language or "fr").startswith("fr")

    @property
    def available(self) -> bool:
        """Return True only when the coordinator has successfully fetched data."""
        return super().available and self.coordinator.data is not None
