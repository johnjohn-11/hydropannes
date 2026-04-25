"""Diagnostics support for Hydro-Pannes."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import HydroPannesDataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with sensitive fields redacted."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    lieu_conso = coordinator.lieu_conso
    masked_lieu = f"****{lieu_conso[-4:]}" if len(lieu_conso) > 4 else "****"

    coordinator_info: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
        "api_compatible": coordinator.api_compatible,
    }

    if hasattr(coordinator, "last_update_success_time"):
        coordinator_info["last_update_success_time"] = (
            coordinator.last_update_success_time.isoformat()
            if coordinator.last_update_success_time
            else None
        )

    # Redact sensitive fields in each history snapshot.
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
        },
        "coordinator": coordinator_info,
        "current_data": _redact_data(coordinator.data) if coordinator.data else None,
        "api_history": api_history,
    }


def _redact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of the API data with the idLieuConso field masked."""
    if not data:
        return {}

    redacted = copy.deepcopy(data)

    if "idLieuConso" in redacted:
        lieu = redacted["idLieuConso"]
        redacted["idLieuConso"] = f"****{lieu[-4:]}" if len(lieu) > 4 else "****"

    return redacted
