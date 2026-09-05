"""Integration setup/unload tests using pytest-homeassistant-custom-component.

The Hydro-Québec API is served by aioclient_mock, so the coordinator's first
refresh runs against a stubbed response and no real socket is opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er, issue_registry as ir
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


async def test_enum_sensor_states_accepted_by_home_assistant(
    hass: HomeAssistant, aioclient_mock, caplog
) -> None:
    """Enum sensors expose slugs that Home Assistant accepts as valid states.

    Home Assistant rejects any state outside a sensor's ``options`` and logs an
    error, so this drives the real state machine rather than the sensor classes
    alone.
    """
    outage = [
        {
            "etat": "N",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "dateDebut": "2024-01-01T00:00:00-05:00",
                    "interruptionPlanifiee": False,
                    "niveauUrgence": "P",
                    "codeCause": "11",
                    "codeIntervention": "L",
                }
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=outage)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Entity ids follow the translated name, so resolve them by unique_id.
    registry = er.async_get(hass)

    def entity_id_for(key: str) -> str:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        assert entity_id is not None, f"no sensor registered for {key}"
        return entity_id

    def state_of(key: str) -> str:
        return hass.states.get(entity_id_for(key)).state

    assert state_of("info_pannes") == "panne_majeure"
    assert state_of("niveau_urgence") == "panne_majeure"
    assert state_of("cause") == "bris_equipement"
    assert state_of("statut_intervention") == "travaux_par_priorite"

    # The raw HQ code survives as an attribute of the cause sensor.
    cause_state = hass.states.get(entity_id_for("cause"))
    assert cause_state.attributes["code_cause"] == "11"
    # Home Assistant advertises the declared options on the entity.
    assert "bris_equipement" in cause_state.attributes["options"]

    # No "provides invalid state" / options complaint from the sensor platform.
    assert "invalid" not in caplog.text.lower()


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


async def test_api_schema_issue_created_and_cleared(hass: HomeAssistant, aioclient_mock) -> None:
    """A missing root field raises a repair issue; recovery clears it."""
    # First response drops required root fields (idLieuConso, interruptions).
    aioclient_mock.get(API_URL.format(LIEU), json=[{"etat": "A"}])
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    issue_id = f"api_incompatible_{entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    # A well-formed response on the next refresh clears the issue.
    aioclient_mock.clear_requests()
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, issue_id) is None
