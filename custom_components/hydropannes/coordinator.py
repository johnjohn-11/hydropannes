"""Data update coordinator for Hydro-Pannes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
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
JSON_LOG_MAX_SIZE_MB = 5

# Root-level fields that must always be present (Option A).
EXPECTED_ROOT_FIELDS = {"etat", "interruptions", "idLieuConso"}

# All interruption fields the integration currently uses (Option C).
# A warning is logged when HQ sends an unknown field, signalling an API evolution.
KNOWN_INTERRUPTION_FIELDS = {
    "dateDebut", "dateFin", "etat", "dateFinEstimeeMin", "dateFinEstimeeMax",
    "dateDebutReport", "dateFinReport", "codeIntervention", "niveauUrgence",
    "nbClient", "codeCause", "codeMunicipal", "datePublication", "codeRemarque",
    "dureePrevu", "probabilite", "interruptionPlanifiee", "typeFinPrevue",
}


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing Hydro-Pannes data fetching and caching."""

    def __init__(self, hass: HomeAssistant, lieu_conso: str) -> None:
        """Initialize the coordinator."""
        self.lieu_conso = lieu_conso
        self.api_compatible = True
        self._last_hashes: dict[str, str] = {}
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

                        if not data or not isinstance(data, list):
                            self.api_compatible = False
                            return self._handle_failure(
                                "API returned invalid data format (expected list)"
                            )

                        result: dict[str, Any] = data[0]

                        # Option A: validate root-level fields that are always present.
                        missing_root = EXPECTED_ROOT_FIELDS - result.keys()
                        if missing_root:
                            if self.api_compatible:
                                _LOGGER.error(
                                    "Structure de l'API Hydro-Québec non reconnue ou modifiée "
                                    "— champs manquants: %s",
                                    missing_root,
                                )
                            self.api_compatible = False
                        else:
                            self.api_compatible = True

                        # Option C: log unknown fields in interruptions when a panne is present.
                        for intr in result.get("interruptions", []):
                            unknown = intr.keys() - KNOWN_INTERRUPTION_FIELDS
                            if unknown:
                                _LOGGER.warning(
                                    "Nouveaux champs API détectés dans une interruption "
                                    "(lieu %s): %s",
                                    self.lieu_conso,
                                    unknown,
                                )

                        self._record_if_changed(result)
                        self._adjust_update_interval(result)
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

    async def _save_json_if_changed(self, lieu_id: str, data: dict[str, Any]) -> None:
        """Append a JSONL log entry only when data has changed since the last write.

        File I/O is dispatched to a thread pool via async_add_executor_job to avoid
        blocking the Home Assistant event loop.
        """
        current_hash = hashlib.md5(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

        if self._last_hashes.get(lieu_id) == current_hash:
            return

        self._last_hashes[lieu_id] = current_hash

        entry = {
            "timestamp": dt_util.utcnow().isoformat(),
            "data": data,
        }
        entry_line = json.dumps(entry) + "\n"
        log_dir = self.hass.config.path("hydropannes_logs")

        await self.hass.async_add_executor_job(
            self._write_log_sync, lieu_id, log_dir, entry_line
        )

    def _write_log_sync(self, lieu_id: str, log_dir: str, entry_line: str) -> None:
        """Write a log entry to disk. Runs in an executor thread, not the event loop."""
        try:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{lieu_id}.jsonl")

            if os.path.exists(log_file):
                size_mb = os.path.getsize(log_file) / (1024 * 1024)
                if size_mb >= JSON_LOG_MAX_SIZE_MB:
                    self._rotate_log(log_file)

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry_line)

            _LOGGER.debug("Logged change for lieu %s", lieu_id)

        except OSError:
            _LOGGER.exception("Failed to write log for lieu %s", lieu_id)

    def _rotate_log(self, log_file: str) -> None:
        """Trim the log file to its most recent half when it exceeds the size limit.

        Called from _write_log_sync; already running in an executor thread.
        """
        try:
            with open(log_file, encoding="utf-8") as f:
                lines = f.readlines()

            keep = lines[len(lines) // 2:]

            with open(log_file, "w", encoding="utf-8") as f:
                f.writelines(keep)

            _LOGGER.info(
                "Rotated %s: kept %d/%d entries",
                log_file,
                len(keep),
                len(lines),
            )
        except OSError:
            _LOGGER.exception("Failed to rotate log file %s", log_file)
