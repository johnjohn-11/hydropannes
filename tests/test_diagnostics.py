"""Diagnostics report tests, run against a loaded entry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyhydropannes.const import API_URL
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hydropannes.const import CONF_LIEU_CONSO, DOMAIN
from custom_components.hydropannes.diagnostics import async_get_config_entry_diagnostics

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

LIEU = "0123456789"
CODE_MUNICIPAL = "99999"
PAYLOAD = [
    {
        "etat": "A",
        "idLieuConso": LIEU,
        "interruptions": [
            {
                "dateDebut": "2026-01-01T08:00:00",
                "dateFin": "2026-01-01T09:00:00",
                "etat": "T",
                "interruptionPlanifiee": False,
                "codeMunicipal": CODE_MUNICIPAL,
            }
        ],
    }
]


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration during tests."""
    yield


async def test_report_masks_the_number_and_the_title(hass: HomeAssistant, aioclient_mock) -> None:
    """The report keeps the last 4 digits of the number, hides the title and leaves the coordinator data intact."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LIEU,
        data={CONF_LIEU_CONSO: LIEU},
        title="75, boulevard René-Lévesque Ouest",
        version=2,
        minor_version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["entry"]["title"] == "**REDACTED**"
    assert report["entry"]["data"] == {"lieu_consommation": "****6789"}
    assert report["current_data"]["idLieuConso"] == "****6789"
    assert [s["data"]["idLieuConso"] for s in report["api_history"]] == ["****6789"]
    assert report["coordinator"]["last_update_success"] is True
    assert report["coordinator"]["total_polls"] == 1
    assert report["coordinator"]["last_error"] is None
    assert report["current_data"]["interruptions"][0]["codeMunicipal"] == "**REDACTED**"
    assert LIEU not in str(report)
    assert CODE_MUNICIPAL not in str(report)
    assert entry.runtime_data.data.raw["idLieuConso"] == LIEU
    assert entry.runtime_data.data.raw["interruptions"][0]["codeMunicipal"] == CODE_MUNICIPAL


async def test_report_hides_the_number_after_an_empty_answer(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """The error kept from an empty list does not carry the number into the report."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=LIEU, data={CONF_LIEU_CONSO: LIEU})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.get(API_URL.format(LIEU), json=[])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["coordinator"]["last_error"]["message"] == "API returned an empty list"
    assert LIEU not in str(report)
