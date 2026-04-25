"""Support for Hydro-Pannes binary sensors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import HydroPannesDataUpdateCoordinator
from .helpers import HydroPannesHelperMixin

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hydro-Pannes binary sensors for a config entry."""
    coordinator: HydroPannesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    nom_lieu = entry.title

    async_add_entities(
        [
            HydroPannesEtatServiceBinarySensor(coordinator, entry, nom_lieu),
            HydroPannesInterventionPlanifieeBinarySensor(coordinator, entry, nom_lieu),
            HydroPannesAPICompatibilityBinarySensor(coordinator, entry, nom_lieu),
        ]
    )


class HydroPannesBinarySensorBase(
    CoordinatorEntity[HydroPannesDataUpdateCoordinator],
    BinarySensorEntity,
    HydroPannesHelperMixin,
):
    """Base class for all Hydro-Pannes binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HydroPannesDataUpdateCoordinator,
        entry: ConfigEntry,
        nom_lieu: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._nom_lieu = nom_lieu

    @property
    def available(self) -> bool:
        """Return True only when the coordinator has successfully fetched data."""
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"HydroPannes {self._nom_lieu}",
            manufacturer="Hydro-Québec",
            model="Info-pannes",
        )


class HydroPannesEtatServiceBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether there is an active service problem."""

    def __init__(
        self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "État du service"
        self._attr_unique_id = f"{entry.entry_id}_etat_service"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        """Return True if there is an active outage, False if normal, None if unknown."""
        if not self.coordinator.data:
            return None
        main_etat = self._get_main_etat()
        if main_etat != "N":
            return False
        if self._get_active_outage():
            return True
        planned = self._get_planned_intervention()
        if planned and self._is_outage_active(planned):
            return True
        return None

    @property
    def icon(self) -> str:
        """Return an icon reflecting the current service state."""
        return "mdi:power-plug-off" if self.is_on else "mdi:power-plug"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the selected interruption."""
        if not self.coordinator.data:
            return {}
        interruptions = self._get_interruptions()
        if not interruptions:
            return {}
        active_interruption = self._get_active_outage()
        if not active_interruption:
            active_interruption = self._get_planned_intervention()
        if not active_interruption:
            active_interruption = interruptions[0]
        return {
            "dateDebut": active_interruption.get("dateDebut"),
            "dateFin": active_interruption.get("dateFin"),
            "dateDebutReport": active_interruption.get("dateDebutReport"),
            "dateFinReport": active_interruption.get("dateFinReport"),
            "dateFinEstimeeMax": active_interruption.get("dateFinEstimeeMax"),
            "etat": active_interruption.get("etat"),
            "interruptionPlanifiee": active_interruption.get("interruptionPlanifiee"),
            "codeIntervention": active_interruption.get("codeIntervention"),
            "niveauUrgence": active_interruption.get("niveauUrgence"),
            "nbClient": active_interruption.get("nbClient"),
            "codeCause": active_interruption.get("codeCause"),
            "codeMunicipal": active_interruption.get("codeMunicipal"),
            "dureePrevu": active_interruption.get("dureePrevu"),
            "typeFinPrevue": active_interruption.get("typeFinPrevue"),
            "attribution": ATTRIBUTION,
        }


class HydroPannesInterventionPlanifieeBinarySensor(HydroPannesBinarySensorBase):
    """Binary sensor indicating whether a planned intervention is active or upcoming."""

    def __init__(
        self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Intervention planifiée"
        self._attr_unique_id = f"{entry.entry_id}_intervention_planifiee"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool | None:
        """Return True if a non-terminated planned intervention exists."""
        if not self.coordinator.data:
            return None
        for intr in self._get_interruptions():
            if self._is_planned_intervention(intr) and not self._is_outage_terminated(intr):
                return True
        return False

    @property
    def icon(self) -> str:
        """Return an icon reflecting the planned intervention state."""
        return "mdi:calendar-clock" if self.is_on else "mdi:calendar-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return key fields from the most relevant planned intervention."""
        if not self.coordinator.data:
            return {}
        interruptions = self._get_interruptions()
        if not interruptions:
            return {}
        planned = next(
            (
                i
                for i in interruptions
                if self._is_planned_intervention(i) and not self._is_outage_terminated(i)
            ),
            None,
        )
        if not planned:
            return {}
        return {
            "dateDebut": planned.get("dateDebut"),
            "dateFin": planned.get("dateFin"),
            "dateDebutReport": planned.get("dateDebutReport"),
            "dateFinReport": planned.get("dateFinReport"),
            "dateFinEstimeeMax": planned.get("dateFinEstimeeMax"),
            "etat": planned.get("etat"),
            "interruptionPlanifiee": planned.get("interruptionPlanifiee"),
            "codeIntervention": planned.get("codeIntervention"),
            "niveauUrgence": planned.get("niveauUrgence"),
            "nbClient": planned.get("nbClient"),
            "codeCause": planned.get("codeCause"),
            "codeMunicipal": planned.get("codeMunicipal"),
            "dureePrevu": planned.get("dureePrevu"),
            "typeFinPrevue": planned.get("typeFinPrevue"),
            "datePublication": planned.get("datePublication"),
            "codeRemarque": planned.get("codeRemarque"),
            "probabilite": planned.get("probabilite"),
            "attribution": ATTRIBUTION,
        }


class HydroPannesAPICompatibilityBinarySensor(HydroPannesBinarySensorBase):
    """Diagnostic binary sensor to monitor API structure changes."""

    def __init__(
        self, coordinator: HydroPannesDataUpdateCoordinator, entry: ConfigEntry, nom_lieu: str
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator, entry, nom_lieu)
        self._attr_name = "Compatibilité API"
        self._attr_unique_id = f"{entry.entry_id}_api_compatibility"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return True (Problem) if the API structure is incompatible."""
        return not self.coordinator.api_compatible

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        return "mdi:api-off" if self.is_on else "mdi:api"
