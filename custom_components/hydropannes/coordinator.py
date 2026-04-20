"""Data update coordinator for Hydro-Pannes."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
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

MAX_RETRIES = 2
RETRY_DELAY = 2  # seconds between retry attempts
ACTIVE_OUTAGE_UPDATE_INTERVAL = 60  # seconds — faster polling during an active outage
API_HISTORY_SIZE = 5  # number of distinct API payloads to keep in memory


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing Hydro-Pannes data fetching and caching."""

    def __init__(self, hass: HomeAssistant, lieu_conso: str) -> None:
        """Initialize the coordinator."""
        self.lieu_conso = lieu_conso
        self.api_compatible = True
        # Ring buffer of the last API_HISTORY_SIZE distinct payloads with timestamps.
        self.api_history: deque[dict[str, Any]] = deque(maxlen=API_HISTORY_SIZE)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from the Hydro-Québec API."""
        url = API_URL.format(self.lieu_conso)
        session = async_get_clientsession(self.hass)

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with asyncio.timeout(10):
                    async with session.get(url) as response:
                        if 500 <= response.status < 600:
                            if attempt < MAX_RETRIES:
                                _LOGGER.debug(
                                    "API returned %s for lieu %s, retry %s/%s",
                                    response.status,
                                    self.lieu_conso,
                                    attempt + 1,
                                    MAX_RETRIES,
                                )
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            return self._handle_failure(
                                f"API returned {response.status} "
                                f"after {MAX_RETRIES + 1} attempts"
                            )

                        if response.status != 200:
                            return self._handle_failure(
                                f"API returned status {response.status}"
                            )

                        data = await response.json()
                        
                        # Vérification de la compatibilité de la structure
                        if not data or not isinstance(data, list):
                            self.api_compatible = False
                            return self._handle_failure("API returned invalid data format (expected list)")

                        result: dict[str, Any] = data[0]
                        
                        # Vérification de la présence d'une clé racine critique (ex: 'etat')
                        if "etat" not in result:
                            if self.api_compatible:
                                _LOGGER.error("Structure de l'API Hydro-Québec non reconnue ou modifiée")
                            self.api_compatible = False
                        else:
                            self.api_compatible = True

                        self._record_if_changed(result)
                        self._adjust_update_interval(result)
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
                _LOGGER.exception("Unexpected error for lieu %s", self.lieu_conso)
                return self._handle_failure(f"Unexpected error: {err}")

        return self._handle_failure("Unknown error")

    def _handle_failure(self, error_msg: str) -> dict[str, Any]:
        """Return stale data on transient failure, or raise UpdateFailed if none exists."""
        if self.data is not None:
            _LOGGER.warning(
                "%s for lieu %s — keeping previous data",
                error_msg,
                self.lieu_conso,
            )
            return dict(self.data)

        _LOGGER.warning(
            "%s for lieu %s — no previous data available",
            error_msg,
            self.lieu_conso,
        )
        raise UpdateFailed(f"Error communicating with API: {error_msg}")

    def _record_if_changed(self, data: dict[str, Any]) -> None:
        """Append a timestamped snapshot to api_history when the payload has changed."""
        if self.api_history and self.api_history[-1]["data"] == data:
            return

        snapshot = {
            "timestamp": dt_util.utcnow().isoformat(),
            "data": data,
        }
        self.api_history.append(snapshot)
        _LOGGER.debug(
            "API data changed for lieu %s (history: %d/%d)",
            self.lieu_conso,
            len(self.api_history),
            API_HISTORY_SIZE,
        )

    def _adjust_update_interval(self, data: dict[str, Any]) -> None:
        """Switch between fast and normal polling based on outage state."""
        target_seconds = (
            ACTIVE_OUTAGE_UPDATE_INTERVAL
            if self._is_active_outage_in_data(data)
            else UPDATE_INTERVAL
        )
        target = timedelta(seconds=target_seconds)
        if self.update_interval != target:
            self.update_interval = target
            _LOGGER.debug(
                "Polling interval set to %ss for lieu %s",
                target_seconds,
                self.lieu_conso,
            )

    def _is_active_outage_in_data(self, data: dict[str, Any]) -> bool:
        """Return True if data contains at least one active (non-terminated) outage."""
        if data.get("etat") != "N":
            return False
        now = dt_util.now()
        for intr in data.get("interruptions", []):
            date_fin_str = intr.get("dateFin")
            if not date_fin_str:
                return True  # no end date means the outage is still ongoing
            dt = dt_util.parse_datetime(date_fin_str)
            if dt and dt_util.as_local(dt) > now:
                return True
        return False
