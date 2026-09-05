"""Coordinator tests using pytest-homeassistant-custom-component.

Covers adaptive polling, change detection/history, and the retry/error
paths, driving the real coordinator against a stubbed API (aioclient_mock).
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.hydropannes.const import (
    API_URL,
    CONF_LIEU_CONSO,
    CONF_NOM_LIEU,
    DOMAIN,
    EVENT_DATA_CHANGED,
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


async def test_change_fires_event_with_payload(hass: HomeAssistant, aioclient_mock) -> None:
    """A payload change fires hydropannes_data_changed once, carrying the payload."""
    events = async_capture_events(hass, EVENT_DATA_CHANGED)
    aioclient_mock.get(API_URL.format(LIEU), json=IDLE_PAYLOAD)
    coordinator = _coordinator(hass)

    await coordinator._async_update_data()
    assert len(events) == 1
    assert events[0].data["lieu_consommation"] == LIEU
    assert events[0].data["data"]["idLieuConso"] == LIEU

    # Unchanged payload on the next poll fires no further event.
    await coordinator._async_update_data()
    assert len(events) == 1


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


async def test_unknown_interruption_field_warns_once(
    hass: HomeAssistant, aioclient_mock, caplog
) -> None:
    """An unknown interruption field is reported once, not on every poll.

    During an outage the coordinator polls every 60 s, so warning per poll
    would flood the log for the whole duration of the panne.
    """
    payload = [
        {
            "etat": "N",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "dateDebut": "2024-01-01T00:00:00-05:00",
                    "interruptionPlanifiee": False,
                    "champTotalementNouveau": 1,
                }
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=payload)
    coordinator = _coordinator(hass)

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            await coordinator._async_update_data()

    warnings = [r for r in caplog.records if "New API fields detected" in r.message]
    assert len(warnings) == 1
    assert "champTotalementNouveau" in warnings[0].message


async def test_last_success_time_is_recorded(hass: HomeAssistant, aioclient_mock) -> None:
    """A successful fetch records the timestamp the DerniereMAJ sensor reads."""
    aioclient_mock.get(API_URL.format(LIEU), json=IDLE_PAYLOAD)
    coordinator = _coordinator(hass)

    assert coordinator.last_success_time is None

    await coordinator._async_update_data()

    assert coordinator.last_success_time is not None


async def test_last_success_time_untouched_by_failure(hass: HomeAssistant, aioclient_mock) -> None:
    """A failed fetch leaves the previous success timestamp in place."""
    aioclient_mock.get(API_URL.format(LIEU), json=IDLE_PAYLOAD)
    coordinator = _coordinator(hass)
    await coordinator._async_update_data()
    first = coordinator.last_success_time

    aioclient_mock.clear_requests()
    aioclient_mock.get(API_URL.format(LIEU), status=404)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.last_success_time == first


async def test_invalid_payload_shape_marks_incompatible(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A non-list payload is rejected and flags the API as incompatible."""
    aioclient_mock.get(API_URL.format(LIEU), json={"not": "a list"})
    coordinator = _coordinator(hass)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.api_compatible is False
