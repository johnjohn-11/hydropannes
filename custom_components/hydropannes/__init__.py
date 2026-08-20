"""The Hydro-Pannes integration.

This module handles the lifecycle of config entries: setup, platform
forwarding, and teardown.

An immediate data refresh can be triggered per entity with the built-in
``homeassistant.update_entity`` service, so no custom refresh service is
provided.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type HydroPannesConfigEntry = ConfigEntry[HydroPannesDataUpdateCoordinator]

# Reject YAML configuration: this integration is set up via config entries only.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: HydroPannesConfigEntry) -> bool:
    """Set up Hydro-Pannes from a config entry.

    Creates a coordinator for the configured lieu de consommation, performs
    the first data fetch, stores the coordinator in ``entry.runtime_data``,
    and forwards setup to all platforms.
    """
    coordinator = HydroPannesDataUpdateCoordinator(hass, entry)

    # Raises ConfigEntryNotReady on failure, which HA will retry automatically.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Reload the entry when its data or options change (e.g. a rename) so the
    # new title takes effect immediately.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: HydroPannesConfigEntry) -> None:
    """Reload the config entry when its data or options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HydroPannesConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
