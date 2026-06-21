"""Diagnostics support for Hydro-Pannes.

Exposes coordinator state and recent API history for the HA diagnostics
download feature.  All sensitive fields (lieu de consommation ID) are
masked before being returned so the report is safe to share publicly in
GitHub issues.

Note: a custom partial-masking helper is used instead of the standard
``async_redact_data`` so that the last 4 digits remain visible — this keeps
multi-location reports diagnosable while still hiding the identifier.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import HydroPannesConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HydroPannesConfigEntry
) -> dict[str, Any]:
    """Build a diagnostics report for a config entry.

    The report contains:
    - Config entry metadata (entry_id, version, title).
    - Coordinator health: last update success, polling interval,
      API compatibility flag, last success timestamp if available,
      and lifetime poll/change/error counters with the last error details.
    - The current API payload (redacted).
    - The last API_HISTORY_SIZE distinct payloads with timestamps (redacted).
    """
    coordinator = entry.runtime_data

    lieu_conso = coordinator.lieu_conso
    masked_lieu = f"****{lieu_conso[-4:]}" if len(lieu_conso) > 4 else "****"

    coordinator_info: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
        # Indicates whether the last API response had the expected schema.
        "api_compatible": coordinator.api_compatible,
        # Whether the opt-in JSONL change log is enabled.
        "json_log_enabled": coordinator.json_log_enabled,
        # Lifetime counters (reset on each HA restart).
        "total_polls": coordinator.total_polls,
        "total_changes": coordinator.total_changes,
        "total_errors": coordinator.total_errors,
        # None if no error has occurred since the last HA restart.
        "last_error": coordinator.last_error,
    }

    if hasattr(coordinator, "last_update_success_time"):
        coordinator_info["last_update_success_time"] = (
            coordinator.last_update_success_time.isoformat()
            if coordinator.last_update_success_time
            else None
        )

    # Deep-copy each history snapshot before redacting so the coordinator's
    # in-memory data is never mutated by the diagnostics call.
    api_history = [
        {
            "timestamp": snapshot["timestamp"],
            "data": _redact_data(snapshot["data"]),
        }
        for snapshot in coordinator.api_history
    ]

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": {
                "lieu_consommation": masked_lieu,
                "nom_lieu": entry.data.get("nom_lieu"),
            },
            "options": dict(entry.options),
        },
        "coordinator": coordinator_info,
        "current_data": _redact_data(coordinator.data) if coordinator.data else None,
        "api_history": api_history,
    }


def _redact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of an API payload with ``idLieuConso`` masked.

    Uses deepcopy to ensure the original coordinator data is never modified,
    even if the dict contains nested mutable objects (e.g. the interruptions
    list).
    """
    if not data:
        return {}

    redacted = copy.deepcopy(data)

    if "idLieuConso" in redacted:
        lieu = redacted["idLieuConso"]
        redacted["idLieuConso"] = f"****{lieu[-4:]}" if len(lieu) > 4 else "****"

    return redacted
