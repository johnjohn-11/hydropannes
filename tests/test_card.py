"""Tests of the dashboard card the integration serves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.setup import async_setup_component
import pytest

from custom_components.hydropannes import CARD_URL
from custom_components.hydropannes.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import ClientSessionGenerator


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests in this module."""


async def test_card_is_served(hass: HomeAssistant, hass_client: ClientSessionGenerator) -> None:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert 'customElements.define("hydropannes-card"' in await response.text()


async def test_setup_without_http(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    assert "http" not in hass.config.components
