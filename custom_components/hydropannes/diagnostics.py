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
    """Return diagnostics for a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry to get diagnostics for.

    Returns:
        Dictionary containing diagnostic information.

    """
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Mask the lieu_conso for privacy (show only last 4 digits)
    lieu_conso = coordinator.lieu_conso
    masked_lieu = f"****{lieu_conso[-4:]}" if len(lieu_conso) > 4 else "****"

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
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_update_success_time": (
                coordinator.last_update_success_time.isoformat()
                if coordinator.last_update_success_time
                else None
            ),
            "update_interval": str(coordinator.update_interval),
        },
        "data": _redact_data(coordinator.data) if coordinator.data else None,
    }


def _redact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive information from the data.

    Args:
        data: Raw API data to redact.

    Returns:
        Data with sensitive information masked.

    """
    if not data:
        return {}

    redacted = dict(data)

    # Mask the idLieuConso
    if "idLieuConso" in redacted:
        lieu = redacted["idLieuConso"]
        redacted["idLieuConso"] = f"****{lieu[-4:]}" if len(lieu) > 4 else "****"

    return redacted
