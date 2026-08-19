"""Integration setup/unload tests using pytest-homeassistant-custom-component.

The Hydro-Québec API is served by aioclient_mock, so the coordinator's first
refresh runs against a stubbed response and no real socket is opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hydropannes.const import (
    API_URL,
    CONF_LIEU_CONSO,
    CONF_NOM_LIEU,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

LIEU = "0123456789"
PAYLOAD = [{"etat": "A", "idLieuConso": LIEU, "interruptions": []}]


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration during tests."""
    yield


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=LIEU,
        data={CONF_LIEU_CONSO: LIEU, CONF_NOM_LIEU: "Maison"},
        title="Maison",
    )


async def test_setup_and_unload(hass: HomeAssistant, aioclient_mock) -> None:
    """A successful first refresh loads the entry, entities, then unloads."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data["idLieuConso"] == LIEU
    # Sensor and binary_sensor entities were created for this location.
    assert hass.states.async_entity_ids()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_api_error(hass: HomeAssistant, aioclient_mock) -> None:
    """A persistent 5xx leaves the entry in SETUP_RETRY (ConfigEntryNotReady)."""
    aioclient_mock.get(API_URL.format(LIEU), status=500)
    entry = _entry()
    entry.add_to_hass(hass)

    # Zero the coordinator's inter-retry backoff to keep the test fast.
    with patch("custom_components.hydropannes.coordinator.RETRY_DELAY", 0):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_refresh_service_registered(hass: HomeAssistant, aioclient_mock) -> None:
    """The hydropannes.refresh service is registered once the entry loads."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "refresh")
