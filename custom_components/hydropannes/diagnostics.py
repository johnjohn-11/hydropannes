"""Diagnostics support for Hydro-Pannes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import HydroPannesDataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Mask the lieu_conso for privacy (show only last 4 digits)
    lieu_conso = coordinator.lieu_conso
    masked_lieu = f"****{lieu_conso[-4:]}" if len(lieu_conso) > 4 else "****"

    # Build coordinator info
    coordinator_info: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
    }

    # Add last_update_success_time if available (HA 2023.9+)
    if hasattr(coordinator, "last_update_success_time"):
        coordinator_info["last_update_success_time"] = (
            coordinator.last_update_success_time.isoformat()
            if coordinator.last_update_success_time
            else None
        )

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
        "data": _redact_data(coordinator.data) if coordinator.data else None,
    }


def _redact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive information from the data."""
    if not data:
        return {}

    redacted = dict(data)

    # Mask the idLieuConso
    if "idLieuConso" in redacted:
        lieu = redacted["idLieuConso"]
        redacted["idLieuConso"] = f"****{lieu[-4:]}" if len(lieu) > 4 else "****"

    return redacted
