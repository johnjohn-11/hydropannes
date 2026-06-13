"""Data update coordinator for Hydro-Pannes.

The coordinator is responsible for:
- Polling the Hydro-Québec Info-pannes API at a configurable interval.
- Switching to faster polling (ACTIVE_OUTAGE_UPDATE_INTERVAL) during an
  active outage and back to the normal interval once it clears.
- Retrying transient HTTP 5xx errors and timeouts up to MAX_RETRIES times.
- Raising UpdateFailed once retries are exhausted, so entities become
  unavailable and the failure is visible (standard HA behaviour).
- Maintaining an in-memory ring buffer (api_history) of the last
  API_HISTORY_SIZE distinct payloads for diagnostics.
- Optionally writing a JSONL change log to the HA config directory for
  troubleshooting (opt-in via the integration options).
- Detecting API structure changes (missing root fields) and flagging unknown
  interruption fields when Hydro-Québec evolves their schema.
- Tracking poll/error/change statistics exposed via the diagnostics report.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta
import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any, NoReturn

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import API_URL, CONF_JSON_LOG, CONF_LIEU_CONSO, DOMAIN, UPDATE_INTERVAL

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 2
RETRY_DELAY = 2  # seconds between retry attempts

# Faster polling interval used while at least one active outage is detected.
ACTIVE_OUTAGE_UPDATE_INTERVAL = 60  # seconds

# Maximum number of distinct API payloads retained in the in-memory ring buffer.
API_HISTORY_SIZE = 5

# Rotate the JSONL log file when it exceeds this size.
JSON_LOG_MAX_SIZE_MB = 5

# ---------------------------------------------------------------------------
# API schema validation
# ---------------------------------------------------------------------------

# Fields that the Hydro-Québec API must always return at the root level.
# Their absence indicates a breaking schema change (Option A validation).
EXPECTED_ROOT_FIELDS = {"etat", "interruptions", "idLieuConso"}

# All interruption-level fields currently consumed by the integration.
# Any field returned by HQ that is NOT in this set triggers a warning log,
# signalling that the API has evolved and the integration may need updating
# (Option C validation — only fires when a panne is active).
KNOWN_INTERRUPTION_FIELDS = {
    "dateDebut",
    "dateFin",
    "etat",
    "dateFinEstimeeMin",
    "dateFinEstimeeMax",
    "dateDebutReport",
    "dateFinReport",
    "codeIntervention",
    "niveauUrgence",
    "nbClient",
    "codeCause",
    "codeMunicipal",
    "datePublication",
    "codeRemarque",
    "dureePrevu",
    "probabilite",
    "interruptionPlanifiee",
    "typeFinPrevue",
}


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing data fetching, caching, and change logging."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry for this lieu de consommation.

        """
        self.lieu_conso: str = entry.data[CONF_LIEU_CONSO]

        # JSONL change log is opt-in (integration options).  Read once here;
        # the update listener reloads the entry when options change.
        self.json_log_enabled: bool = entry.options.get(CONF_JSON_LOG, False)

        # Tracks whether the last successful API response had the expected
        # root-level schema.  True until proven otherwise.
        self.api_compatible: bool = True

        # Hash of the last payload, used for change detection.
        self._last_hash: str | None = None

        # Ring buffer of the most recent distinct API payloads with timestamps,
        # exposed to the diagnostics module.
        self.api_history: deque[dict[str, Any]] = deque(maxlen=API_HISTORY_SIZE)

        # ---------------------------------------------------------------------------
        # Diagnostic counters — reset on each HA restart (in-memory only).
        # ---------------------------------------------------------------------------

        # Total number of API calls attempted (including retries).
        self.total_polls: int = 0

        # Number of calls that resulted in a payload change.
        self.total_changes: int = 0

        # Number of calls that ended in a non-recoverable error
        # (after all retries were exhausted).
        self.total_errors: int = 0

        # Details of the most recent error, or None if no error has occurred.
        self.last_error: dict[str, str] | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    # -----------------------------------------------------------------------
    # Core update loop
    # -----------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest outage data from the Hydro-Québec API.

        Implements a retry loop for transient 5xx errors and network
        timeouts.  On persistent failure, raises UpdateFailed; HA then marks
        entities unavailable and keeps retrying on the normal schedule.
        """
        self.total_polls += 1

        url = API_URL.format(self.lieu_conso)
        session = async_get_clientsession(self.hass)

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with asyncio.timeout(10):
                    async with session.get(url) as response:
                        # Retry on server-side errors; fail immediately on
                        # client errors (4xx) since retrying would not help.
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
                            self._raise_failure(
                                f"API returned {response.status} after {MAX_RETRIES + 1} attempts"
                            )

                        if response.status != 200:
                            self._raise_failure(f"API returned status {response.status}")

                        data = await response.json()

                        if not data or not isinstance(data, list):
                            self.api_compatible = False
                            self._raise_failure("API returned invalid data format (expected list)")

                        result: dict[str, Any] = data[0]

                        # --- Option A: validate required root-level fields ---
                        missing_root = EXPECTED_ROOT_FIELDS - result.keys()
                        if missing_root:
                            if self.api_compatible:
                                # Log once per transition to avoid log spam.
                                _LOGGER.error(
                                    "Structure de l'API Hydro-Québec non reconnue ou "
                                    "modifiée — champs manquants: %s",
                                    missing_root,
                                )
                            self.api_compatible = False
                        else:
                            self.api_compatible = True

                        # --- Option C: warn on unknown interruption fields ---
                        # Only fires during an active panne (interruptions list
                        # is empty otherwise, so no false positives).
                        for intr in result.get("interruptions", []):
                            unknown = intr.keys() - KNOWN_INTERRUPTION_FIELDS
                            if unknown:
                                _LOGGER.warning(
                                    "Nouveaux champs API détectés dans une interruption "
                                    "(lieu %s): %s — le schéma HQ a peut-être évolué.",
                                    self.lieu_conso,
                                    unknown,
                                )

                        # Compute hash once; reused for both the in-memory
                        # history check and the disk log write.
                        current_hash = hashlib.md5(
                            json.dumps(result, sort_keys=True).encode(),
                            usedforsecurity=False,
                        ).hexdigest()
                        changed = self._last_hash != current_hash
                        if changed:
                            self._last_hash = current_hash
                            self.total_changes += 1
                            self._append_history(result)

                        self._adjust_update_interval(result)

                        if changed and self.json_log_enabled:
                            await self._write_log(self.lieu_conso, result)

                        return result

            except UpdateFailed:
                # Raised by _raise_failure inside the try block; never retry.
                raise

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
                self._raise_failure("Timeout after retries")

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
                self._raise_failure(f"Connection error: {err}")

            except Exception as err:
                _LOGGER.exception("Unexpected error for lieu %s", self.lieu_conso)
                self._raise_failure(f"Unexpected error: {err}")

        self._raise_failure("Unknown error")

    # -----------------------------------------------------------------------
    # Failure handling
    # -----------------------------------------------------------------------

    def _raise_failure(self, error_msg: str) -> NoReturn:
        """Record error details for diagnostics and raise UpdateFailed.

        Raising UpdateFailed is the standard HA pattern: the coordinator
        keeps its previous ``data`` in memory, ``last_update_success``
        becomes False, entities go unavailable, and the next scheduled
        refresh retries automatically.  Transient hiccups are already
        absorbed by the in-loop retry logic (MAX_RETRIES).
        """
        self.total_errors += 1
        self.last_error = {
            "timestamp": dt_util.utcnow().isoformat(),
            "message": error_msg,
        }
        raise UpdateFailed(f"Error communicating with API: {error_msg}")

    # -----------------------------------------------------------------------
    # History and polling management
    # -----------------------------------------------------------------------

    def _append_history(self, data: dict[str, Any]) -> None:
        """Append a timestamped snapshot to the in-memory history ring buffer.

        Called only when the payload has changed (caller guarantees this).
        The deque automatically evicts the oldest entry when full.
        """
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
        """Switch between fast and normal polling intervals.

        Uses ACTIVE_OUTAGE_UPDATE_INTERVAL (60 s) during an active outage for
        more responsive end-of-panne detection, and falls back to the normal
        UPDATE_INTERVAL (180 s) otherwise.
        """
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
        """Return True if the payload contains at least one active outage.

        An outage is considered active when:
        - The root-level ``etat`` is ``"N"`` (non-alimenté), AND
        - At least one interruption has no ``dateFin`` or a ``dateFin`` in
          the future.

        This is intentionally separate from the helper mixin used by sensors,
        because it operates on a raw dict rather than through coordinator.data.
        """
        if data.get("etat") != "N":
            return False
        now = dt_util.now()
        for intr in data.get("interruptions", []):
            date_fin_str = intr.get("dateFin")
            if not date_fin_str:
                # No end date → outage is still ongoing.
                return True
            dt = dt_util.parse_datetime(date_fin_str)
            if dt and dt_util.as_local(dt) > now:
                return True
        return False

    # -----------------------------------------------------------------------
    # JSONL change log — opt-in (disk I/O runs in an executor thread)
    # -----------------------------------------------------------------------

    async def _write_log(self, lieu_id: str, data: dict[str, Any]) -> None:
        """Asynchronously append a JSONL entry to the change log.

        Only called when ``json_log_enabled`` is True (integration options).
        File I/O is dispatched to a thread-pool executor via
        async_add_executor_job so it does not block the HA event loop.
        Called only when the payload has changed.
        """
        entry = {
            "timestamp": dt_util.utcnow().isoformat(),
            "data": data,
        }
        entry_line = json.dumps(entry) + "\n"
        log_dir = self.hass.config.path("hydropannes_logs")

        await self.hass.async_add_executor_job(self._write_log_sync, lieu_id, log_dir, entry_line)

    def _write_log_sync(self, lieu_id: str, log_dir: str, entry_line: str) -> None:
        """Write a log entry to disk.

        Runs in an executor thread (not the event loop).  Rotates the file
        when it exceeds JSON_LOG_MAX_SIZE_MB to prevent unbounded growth.
        """
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
        """Trim the log file to its most recent half.

        Called from _write_log_sync; already running in an executor thread.
        Discards the oldest 50 % of entries to balance retention with disk use.
        """
        try:
            with open(log_file, encoding="utf-8") as f:
                lines = f.readlines()

            keep = lines[len(lines) // 2 :]

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
