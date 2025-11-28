"""The Hydro-Pannes integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_URL, CONF_LIEU_CONSO, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hydro-Pannes from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = HydroPannesDataUpdateCoordinator(
        hass,
        entry.data[CONF_LIEU_CONSO],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Hydro-Pannes data.

    When the API returns empty data or is unreachable, UpdateFailed is raised.
    This causes the coordinator to keep the last known valid data and
    prevents sensors from being updated with invalid/empty values.
    """

    def __init__(self, hass: HomeAssistant, lieu_conso: str) -> None:
        """Initialize the coordinator."""
        self.lieu_conso = lieu_conso
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self):
        """Fetch data from the Hydro-Québec API.

        If the API returns empty data or is unreachable, raise UpdateFailed
        to keep the last known valid data in Home Assistant.
        """
        url = API_URL.format(self.lieu_conso)

        try:
            async with async_timeout.timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            _LOGGER.warning(
                                "API returned status %s for lieu %s",
                                response.status,
                                self.lieu_conso,
                            )
                            raise UpdateFailed(
                                f"Error communicating with API: HTTP {response.status}"
                            )

                        data = await response.json()

                        # Validate that we received data
                        if not data or len(data) == 0:
                            _LOGGER.warning(
                                "API returned empty data for lieu %s",
                                self.lieu_conso,
                            )
                            raise UpdateFailed("API returned empty data")

                        _LOGGER.debug(
                            "Successfully fetched data for lieu %s",
                            self.lieu_conso,
                        )
                        return data[0]

        except aiohttp.ClientError as err:
            _LOGGER.warning(
                "Connection error for lieu %s: %s",
                self.lieu_conso,
                err,
            )
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        except TimeoutError as err:
            _LOGGER.warning(
                "Timeout fetching data for lieu %s",
                self.lieu_conso,
            )
            raise UpdateFailed("Timeout communicating with API") from err

        except Exception as err:
            _LOGGER.exception(
                "Unexpected error fetching data for lieu %s",
                self.lieu_conso,
            )
            raise UpdateFailed(f"Unexpected error: {err}") from err
