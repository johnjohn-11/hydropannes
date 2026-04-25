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

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import CONF_LIEU_CONSO, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

SERVICE_REFRESH = "refresh"
SERVICE_REFRESH_SCHEMA = vol.Schema(
    {
        # When omitted, all configured locations are refreshed simultaneously.
        vol.Optional("entry_id"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hydro-Pannes from a config entry.

    Creates a coordinator for the configured lieu de consommation, performs
    the first data fetch, forwards setup to all platforms, and registers the
    refresh service on the first call.
    """
    hass.data.setdefault(DOMAIN, {})

    coordinator = HydroPannesDataUpdateCoordinator(
        hass,
        entry.data[CONF_LIEU_CONSO],
    )

    # Raises ConfigEntryNotReady on failure, which HA will retry automatically.
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the service only once regardless of how many locations are configured.
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):

        async def _handle_refresh(call: ServiceCall) -> None:
            """Force an immediate data refresh for one or all locations.

            If ``entry_id`` is provided, only that coordinator is refreshed.
            Otherwise all coordinators are refreshed concurrently via
            asyncio.gather to avoid blocking the event loop sequentially.
            """
            entry_id: str | None = call.data.get("entry_id")

            if entry_id:
                if coord := hass.data[DOMAIN].get(entry_id):
                    await coord.async_request_refresh()
                else:
                    _LOGGER.warning("Refresh service called with unknown entry_id: %s", entry_id)
            else:
                await asyncio.gather(
                    *[
                        coord.async_request_refresh()
                        for coord in hass.data[DOMAIN].values()
                        if isinstance(coord, HydroPannesDataUpdateCoordinator)
                    ]
                )

        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH,
            _handle_refresh,
            schema=SERVICE_REFRESH_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Unloads all platforms and removes the coordinator from the shared store.
    The refresh service is removed when no more locations remain configured.
    """
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH)

    return unload_ok
