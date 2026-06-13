"""The Hydro-Pannes integration.

This module handles the lifecycle of config entries: setup, platform
forwarding, and teardown.  It also registers the ``hydropannes.refresh``
service, which lets users trigger an immediate data pull from the
Hydro-Québec API for one or all configured locations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type HydroPannesConfigEntry = ConfigEntry[HydroPannesDataUpdateCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_REFRESH = "refresh"
SERVICE_REFRESH_SCHEMA = vol.Schema(
    {
        # When omitted, all configured locations are refreshed simultaneously.
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hydro-Pannes integration (register services once).

    Registering the service here — rather than in async_setup_entry — means
    it exists exactly once regardless of how many locations are configured,
    and no manual removal is needed when entries are unloaded.
    """

    async def _handle_refresh(call: ServiceCall) -> None:
        """Force an immediate data refresh for one or all locations."""
        entry_id: str | None = call.data.get("entry_id")

        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is None
                or entry.domain != DOMAIN
                or entry.state is not ConfigEntryState.LOADED
            ):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="entry_not_found",
                    translation_placeholders={"entry_id": entry_id},
                )
            await entry.runtime_data.async_request_refresh()
            return

        await asyncio.gather(
            *(
                entry.runtime_data.async_request_refresh()
                for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            )
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        _handle_refresh,
        schema=SERVICE_REFRESH_SCHEMA,
    )

    return True


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

    # Reload the entry when data/options change (rename, JSONL logging toggle)
    # so the new title and options take effect immediately.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: HydroPannesConfigEntry) -> None:
    """Reload the config entry when its data or options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HydroPannesConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
