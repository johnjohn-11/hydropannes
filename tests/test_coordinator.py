"""Coordinator tests using pytest-homeassistant-custom-component.

Covers adaptive polling, change detection/history, and the retry/error
paths, driving the real coordinator against a stubbed API (aioclient_mock).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hydropannes.const import (
    API_URL,
    CONF_LIEU_CONSO,
    CONF_NOM_LIEU,
    DOMAIN,
    UPDATE_INTERVAL,
)
from custom_components.hydropannes.coordinator import (
    ACTIVE_OUTAGE_UPDATE_INTERVAL,
    HydroPannesDataUpdateCoordinator,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

LIEU = "0123456789"

ACTIVE_PAYLOAD = [
    {
        "etat": "N",
        "idLieuConso": LIEU,
        "interruptions": [
            {"dateDebut": "2024-01-01T00:00:00-05:00", "interruptionPlanifiee": False}
        ],
    }
]
IDLE_PAYLOAD = [{"etat": "A", "idLieuConso": LIEU, "interruptions": []}]


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration during tests."""
    yield


def _coordinator(hass: HomeAssistant) -> HydroPannesDataUpdateCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LIEU,
        data={CONF_LIEU_CONSO: LIEU, CONF_NOM_LIEU: "Maison"},
    )
    entry.add_to_hass(hass)
    return HydroPannesDataUpdateCoordinator(hass, entry)


async def test_polling_speeds_up_during_active_outage(hass: HomeAssistant, aioclient_mock) -> None:
    """An active outage switches the coordinator to the fast interval."""
    aioclient_mock.get(API_URL.format(LIEU), json=ACTIVE_PAYLOAD)
    coordinator = _coordinator(hass)

    await coordinator._async_update_data()

    assert coordinator.update_interval == timedelta(seconds=ACTIVE_OUTAGE_UPDATE_INTERVAL)


async def test_polling_uses_normal_interval_without_outage(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """No active outage keeps the coordinator on the normal interval."""
    aioclient_mock.get(API_URL.format(LIEU), json=IDLE_PAYLOAD)
    coordinator = _coordinator(hass)

    await coordinator._async_update_data()

    assert coordinator.update_interval == timedelta(seconds=UPDATE_INTERVAL)


async def test_change_detection_and_history(hass: HomeAssistant, aioclient_mock) -> None:
    """Identical consecutive payloads are counted once and stored once."""
    aioclient_mock.get(API_URL.format(LIEU), json=IDLE_PAYLOAD)
    coordinator = _coordinator(hass)

    await coordinator._async_update_data()
    assert coordinator.total_changes == 1
    assert len(coordinator.api_history) == 1

    # Same payload again: no new change recorded, history unchanged.
    await coordinator._async_update_data()
    assert coordinator.total_changes == 1
    assert len(coordinator.api_history) == 1
    assert coordinator.total_polls == 2


async def test_persistent_server_error_raises_and_records(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A persistent 5xx exhausts retries, raises UpdateFailed, records the error."""
    aioclient_mock.get(API_URL.format(LIEU), status=500)
    coordinator = _coordinator(hass)

    with (
        patch("custom_components.hydropannes.coordinator.RETRY_DELAY", 0),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()

    assert coordinator.total_errors == 1
    assert coordinator.last_error is not None
    assert coordinator.last_error["message"]


async def test_client_error_fails_without_retry(hass: HomeAssistant, aioclient_mock) -> None:
    """A 4xx fails immediately without entering the retry loop."""
    aioclient_mock.get(API_URL.format(LIEU), status=404)
    coordinator = _coordinator(hass)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # One poll attempt, no retries for a client error.
    assert coordinator.total_polls == 1
    assert len(aioclient_mock.mock_calls) == 1


async def test_invalid_payload_shape_marks_incompatible(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A non-list payload is rejected and flags the API as incompatible."""
    aioclient_mock.get(API_URL.format(LIEU), json={"not": "a list"})
    coordinator = _coordinator(hass)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.api_compatible is False
