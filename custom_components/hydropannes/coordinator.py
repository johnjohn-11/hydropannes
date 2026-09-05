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
- Firing a ``hydropannes_data_changed`` bus event, carrying the full payload,
  whenever a location's data changes, so users can log or react to changes
  from their own automations.
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
from typing import TYPE_CHECKING, Any, NoReturn

import aiohttp
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import API_URL, CONF_LIEU_CONSO, DOMAIN, EVENT_DATA_CHANGED, UPDATE_INTERVAL

if TYPE_CHECKING:
    from datetime import datetime

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
    "idInterruption",
    "nbClientsInclusDansAutrePanne",
    "repriseGraduellePossible",
}


class HydroPannesDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing data fetching, caching, and change notification."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            entry: The config entry for this lieu de consommation.

        """
        self.lieu_conso: str = entry.data[CONF_LIEU_CONSO]

        # Captured here so the change event doesn't rely on self.config_entry
        # (typed Optional by the base coordinator).
        self._entry_id: str = entry.entry_id

        # Tracks whether the last successful API response had the expected
        # root-level schema.  True until proven otherwise.
        self.api_compatible: bool = True

        # Stable ids for the repair issues raised for this location: one for a
        # payload whose shape is not the expected list, one for a payload that
        # is a list but no longer carries the expected root fields.
        self._api_issue_id: str = f"api_incompatible_{entry.entry_id}"
        self._invalid_response_issue_id: str = f"api_invalid_response_{entry.entry_id}"

        # Whether the invalid-response repair issue is currently raised.
        self._invalid_response_flagged: bool = False

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

        # UTC timestamp of the most recent successful fetch. Consumed by the
        # "Dernière MAJ" sensor and the diagnostics report; the base
        # DataUpdateCoordinator exposes no such attribute.
        self.last_success_time: datetime | None = None

        # Interruption field names already reported as unknown, so a schema
        # change is logged once instead of on every poll.
        self._warned_unknown_fields: set[str] = set()

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
                            # Surface this through Repairs too: the update
                            # fails, so entities other than the API-compatibility
                            # sensor go unavailable and cannot report it.
                            self._flag_invalid_response()
                            self._raise_failure("API returned invalid data format (expected list)")

                        result: dict[str, Any] = data[0]

                        # A well-formed list clears the invalid-response issue.
                        self._clear_invalid_response()

                        # --- Option A: validate required root-level fields ---
                        missing_root = EXPECTED_ROOT_FIELDS - result.keys()
                        if missing_root:
                            if self.api_compatible:
                                # Log once per transition to avoid log spam.
                                _LOGGER.error(
                                    "Unrecognized or changed Hydro-Québec API structure "
                                    "— missing fields: %s",
                                    missing_root,
                                )
                            self.api_compatible = False
                            # Surface the breaking change to the user via Repairs.
                            ir.async_create_issue(
                                self.hass,
                                DOMAIN,
                                self._api_issue_id,
                                is_fixable=False,
                                severity=ir.IssueSeverity.WARNING,
                                translation_key="api_schema_changed",
                                translation_placeholders={
                                    "missing_fields": ", ".join(sorted(missing_root)),
                                },
                            )
                        else:
                            if not self.api_compatible:
                                # Schema recovered — clear the repair issue.
                                ir.async_delete_issue(self.hass, DOMAIN, self._api_issue_id)
                            self.api_compatible = True

                        # --- Option C: warn on unknown interruption fields ---
                        # Only fires during an active panne (interruptions list
                        # is empty otherwise, so no false positives).
                        for intr in result.get("interruptions", []):
                            unknown = intr.keys() - KNOWN_INTERRUPTION_FIELDS
                            # Warn once per field name: during an outage the
                            # coordinator polls every 60 s, so warning on each
                            # poll would flood the log for as long as it lasts.
                            new_fields = unknown - self._warned_unknown_fields
                            if new_fields:
                                self._warned_unknown_fields |= new_fields
                                _LOGGER.warning(
                                    "New API fields detected in an interruption (lieu %s): "
                                    "%s — the Hydro-Québec schema may have evolved.",
                                    self.lieu_conso,
                                    new_fields,
                                )

                        # Compute the payload hash once for change detection.
                        current_hash = hashlib.md5(
                            json.dumps(result, sort_keys=True).encode(),
                            usedforsecurity=False,
                        ).hexdigest()
                        changed = self._last_hash != current_hash
                        if changed:
                            self._last_hash = current_hash
                            self.total_changes += 1
                            self._append_history(result)
                            self._fire_change_event(result)

                        self._adjust_update_interval(result)

                        self.last_success_time = dt_util.utcnow()

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
    # API response validation
    # -----------------------------------------------------------------------

    def _flag_invalid_response(self) -> None:
        """Mark the API incompatible and raise a repair issue.

        Called when the payload is not the expected non-empty list. Unlike a
        missing root field, this also fails the update, so every entity except
        the API-compatibility sensor goes unavailable — Repairs is then the
        only place the user can see what happened.
        """
        self.api_compatible = False
        if self._invalid_response_flagged:
            return
        self._invalid_response_flagged = True
        _LOGGER.error(
            "Hydro-Québec API returned an unexpected payload shape for lieu %s "
            "(expected a non-empty list)",
            self.lieu_conso,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._invalid_response_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="api_invalid_response",
        )

    def _clear_invalid_response(self) -> None:
        """Clear the invalid-response repair issue once the payload is sane."""
        if not self._invalid_response_flagged:
            return
        self._invalid_response_flagged = False
        ir.async_delete_issue(self.hass, DOMAIN, self._invalid_response_issue_id)

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
    # Change notification
    # -----------------------------------------------------------------------

    def _fire_change_event(self, data: dict[str, Any]) -> None:
        """Fire a bus event carrying the full payload on each change.

        Called only when the payload has changed (caller guarantees this).
        Users can subscribe to ``hydropannes_data_changed`` to log or react to
        changes — e.g. append them to a file via the File integration — instead
        of the integration writing to disk itself.
        """
        self.hass.bus.async_fire(
            EVENT_DATA_CHANGED,
            {
                "entry_id": self._entry_id,
                "lieu_consommation": self.lieu_conso,
                "timestamp": dt_util.utcnow().isoformat(),
                "data": data,
            },
        )
