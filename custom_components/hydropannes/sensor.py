"""Support for Hydro-Pannes sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


@dataclass(frozen=True, kw_only=True)
class HydroPannesSensorEntityDescription(SensorEntityDescription):
    """Describes Hydro-Pannes sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSOR_TYPES: tuple[HydroPannesSensorEntityDescription, ...] = (
    HydroPannesSensorEntityDescription(
        key="outage_info",
        name="Info-pannes",
        icon="mdi:information-outline",
        value_fn=lambda data: data.get("etat"),
    ),
    HydroPannesSensorEntityDescription(
        key="affected_customers",
        name="Clients affectés",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("nbClient"),
    ),
    HydroPannesSensorEntityDescription(
        key="outage_duration",
        name="Durée de la panne",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda data: data.get("duree"),
    ),
    HydroPannesSensorEntityDescription(
        key="intervention_status",
        name="Statut de l'intervention",
        icon="mdi:progress-wrench",
        value_fn=lambda data: data.get("statutIntervention"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hydro-Pannes sensors."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.title

    entities: list[CoordinatorEntity[HydroPannesDataUpdateCoordinator]] = [
        HydroPannesSensor(coordinator, description, entry, nom_lieu)
        for description in SENSOR_TYPES
    ]

    entities.extend([
        HydroPannesTimeSensor(coordinator, entry, nom_lieu),
        HydroPannesStartTimeSensor(coordinator, entry, nom_lieu),
    ])

    async_add_entities(entities)


class HydroPannesSensor(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    SensorEntity,
    HydroPannesHelperMixin,
):
    """Representation of a Hydro-Pannes sensor."""

    _attr_has_entity_name = True
    entity_description: HydroPannesSensorEntityDescription

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        description: HydroPannesSensorEntityDescription,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._nom_lieu = nom_lieu
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Hydro-Pannes {nom_lieu}",
            "manufacturer": "Hydro-Québec (Custom)",
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        data = self._get_current_interruption()
        if not data:
            return None

        val = self.entity_description.value_fn(data)

        if self.entity_description.key == "affected_customers":
            return int(val) if val is not None else None

        return str(val) if val is not None else None


class HydroPannesTimeSensor(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    SensorEntity,
    HydroPannesHelperMixin,
):
    """Sensor for the estimated restoration time."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Délai avant rétablissement"
        self._attr_unique_id = f"{entry.entry_id}_restoration_time"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Hydro-Pannes {nom_lieu}",
        }

    @property
    def native_value(self) -> datetime | None:
        """Return the estimated restoration time."""
        data = self._get_current_interruption()
        if not data:
            return None

        res = data.get("dateFin")
        if not res:
            return None

        return dt_util.parse_datetime(str(res))


class HydroPannesStartTimeSensor(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    SensorEntity,
    HydroPannesHelperMixin,
):
    """Sensor for the outage start time."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Début de l'interruption"
        self._attr_unique_id = f"{entry.entry_id}_start_time"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Hydro-Pannes {nom_lieu}",
        }

    @property
    def native_value(self) -> datetime | None:
        """Return the start time of the interruption."""
        data = self._get_current_interruption()
        if not data:
            return None

        res = data.get("dateDebut")
        if not res:
            return None

        return dt_util.parse_datetime(str(res))
