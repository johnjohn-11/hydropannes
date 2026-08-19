"""End-to-end config-flow tests using pytest-homeassistant-custom-component.

These drive the real Home Assistant flow machinery (unlike the mixin unit
tests, which stub the coordinator). The Hydro-Québec API is never contacted:
validate_input and async_setup_entry are patched so no socket is opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hydropannes.config_flow import (
    CannotConnect,
    InvalidFormat,
    InvalidLieuConso,
)
from custom_components.hydropannes.const import CONF_LIEU_CONSO, CONF_NOM_LIEU, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_VALIDATE = "custom_components.hydropannes.config_flow.validate_input"
_SETUP = "custom_components.hydropannes.async_setup_entry"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration during tests."""
    yield


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """A valid number creates a config entry titled with the location name."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        patch(_VALIDATE, return_value={"title": "Maison"}),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maison"
    assert result["data"] == {CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"}


async def test_user_flow_strips_whitespace(hass: HomeAssistant) -> None:
    """Leading/trailing whitespace on the number is stripped before storage."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(_VALIDATE, return_value={"title": "Maison"}) as validate,
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "  0123456789  ", CONF_NOM_LIEU: "Maison"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LIEU_CONSO] == "0123456789"
    # validate_input receives the already-stripped value.
    assert validate.call_args.args[1][CONF_LIEU_CONSO] == "0123456789"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidFormat, {CONF_LIEU_CONSO: "invalid_format"}),
        (CannotConnect, {"base": "cannot_connect"}),
        (InvalidLieuConso, {"base": "invalid_lieu"}),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, error, expected) -> None:
    """Each validation failure maps to the right form error and re-shows it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(_VALIDATE, side_effect=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == expected


async def test_user_flow_duplicate_aborts(hass: HomeAssistant) -> None:
    """Configuring a number that already exists aborts the flow."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="0123456789",
        data={CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(_VALIDATE, return_value={"title": "Chalet"}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Chalet"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_number(hass: HomeAssistant) -> None:
    """Reconfigure replaces the number and unique_id on the same entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="0123456789",
        data={CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"},
        title="Maison",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with (
        patch(_VALIDATE, return_value={"title": "Maison"}),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LIEU_CONSO: "9876543210"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_LIEU_CONSO] == "9876543210"
    assert entry.unique_id == "9876543210"
    # The friendly name is untouched by reconfigure.
    assert entry.data[CONF_NOM_LIEU] == "Maison"


async def test_reconfigure_to_other_entry_number_aborts(hass: HomeAssistant) -> None:
    """Reconfiguring to a number owned by another entry is blocked."""
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1111111111",
        data={CONF_LIEU_CONSO: "1111111111", CONF_NOM_LIEU: "Chalet"},
    )
    other.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="0123456789",
        data={CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    with patch(_VALIDATE, return_value={"title": "Maison"}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LIEU_CONSO: "1111111111"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # Original entry is unchanged.
    assert entry.data[CONF_LIEU_CONSO] == "0123456789"
