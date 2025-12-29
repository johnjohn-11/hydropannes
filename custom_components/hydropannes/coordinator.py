"""Data update coordinator for Hydro-Pannes."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import API_URL, DOMAIN, UPDATE_INTERVAL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Retry config for transient server errors (5xx)
MAX_RETRIES = 2
RETRY_DELAY = 2  # seconds


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Hydro-Pannes data."""

    def __init__(self, hass: HomeAssistant, lieu_conso: str) -> None:
        """Initialize the coordinator."""
        self.lieu_conso = lieu_conso
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Hydro-Québec API."""
        url = API_URL.format(self.lieu_conso)
        session = async_get_clientsession(self.hass)

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with asyncio.timeout(10):
                    async with session.get(url) as response:
                        # Retry on server errors (5xx)
                        if 500 <= response.status < 600:
                            if attempt < MAX_RETRIES:
                                _LOGGER.debug(
                                    "API returned status %s for lieu %s, retry %s/%s",
                                    response.status,
                                    self.lieu_conso,
                                    attempt + 1,
                                    MAX_RETRIES,
                                )
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            # All retries failed - keep previous data if available
                            return self._handle_failure(
                                f"API returned status {response.status} "
                                f"after {MAX_RETRIES + 1} attempts"
                            )

                        if response.status != 200:
                            return self._handle_failure(
                                f"API returned status {response.status}"
                            )

                        data = await response.json()

                        # Validate that we received data
                        if not data:
                            return self._handle_failure("API returned empty data")

                        _LOGGER.debug(
                            "Successfully fetched data for lieu %s",
                            self.lieu_conso,
                        )
                        return data[0]

            except TimeoutError:
                if attempt < MAX_RETRIES:
                    _LOGGER.debug(
                        "Timeout for lieu %s, retry %s/%s",
                        self.lieu_conso,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return self._handle_failure("Timeout after retries")

            except aiohttp.ClientError as err:
                if attempt < MAX_RETRIES:
                    _LOGGER.debug(
                        "Connection error for lieu %s: %s, retry %s/%s",
                        self.lieu_conso,
                        err,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return self._handle_failure(f"Connection error: {err}")

            except Exception as err:
                _LOGGER.exception(
                    "Unexpected error fetching data for lieu %s",
                    self.lieu_conso,
                )
                return self._handle_failure(f"Unexpected error: {err}")

        # Should not reach here, but just in case
        return self._handle_failure("Unknown error")

    def _handle_failure(self, error_msg: str) -> dict[str, Any]:
        """Handle API failure by keeping previous data or raising UpdateFailed."""
        if self.data is not None:
            _LOGGER.warning(
                "%s for lieu %s - keeping previous data",
                error_msg,
                self.lieu_conso,
            )
            return dict(self.data)

        _LOGGER.warning(
            "%s for lieu %s - no previous data available",
            error_msg,
            self.lieu_conso,
        )
        raise UpdateFailed(f"Error communicating with API: {error_msg}")
