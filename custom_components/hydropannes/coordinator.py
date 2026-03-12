"""Data update coordinator for Hydro-Pannes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import API_URL, DOMAIN, UPDATE_INTERVAL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Retry config for transient server errors (5xx)
MAX_RETRIES = 2
RETRY_DELAY = 2  # seconds

# JSON logging config
JSON_LOG_MAX_SIZE_MB = 5


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Hydro-Pannes data."""

    def __init__(self, hass: HomeAssistant, lieu_conso: str) -> None:
        """Initialize the coordinator."""
        self.lieu_conso = lieu_conso
        self._last_hashes: dict[str, str] = {}
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
                        result: dict[str, Any] = data[0]
                        await self._save_json_if_changed(self.lieu_conso, result)
                        return result

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

    async def _save_json_if_changed(self, lieu_id: str, data: dict[str, Any]) -> None:
        """Save raw JSON to JSONL log only if data has changed since last entry."""
        try:
            log_dir = self.hass.config.path("hydropannes_logs")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{lieu_id}.jsonl")

            # Compute hash of current data
            current_hash = hashlib.md5(
                json.dumps(data, sort_keys=True).encode()
            ).hexdigest()

            # Skip if data hasn't changed
            if self._last_hashes.get(lieu_id) == current_hash:
                return

            self._last_hashes[lieu_id] = current_hash

            # Rotate if file exceeds size limit
            if os.path.exists(log_file):
                size_mb = os.path.getsize(log_file) / (1024 * 1024)
                if size_mb >= JSON_LOG_MAX_SIZE_MB:
                    self._rotate_log(log_file)

            entry = {
                "timestamp": dt_util.utcnow().isoformat(),
                "data": data,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            _LOGGER.debug("JSON change logged for lieu %s", lieu_id)

        except OSError:
            _LOGGER.exception("Failed to write JSON log for lieu %s", lieu_id)

    def _rotate_log(self, log_file: str) -> None:
        """Keep only the most recent half of log entries."""
        try:
            with open(log_file, encoding="utf-8") as f:
                lines = f.readlines()

            keep = lines[len(lines) // 2 :]

            with open(log_file, "w", encoding="utf-8") as f:
                f.writelines(keep)

            _LOGGER.info(
                "Rotated log file %s: kept %d/%d entries",
                log_file,
                len(keep),
                len(lines),
            )
        except OSError:
            _LOGGER.exception("Failed to rotate log file %s", log_file)
