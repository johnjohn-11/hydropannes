"""End-to-end config-flow tests using pytest-homeassistant-custom-component.

These drive the real Home Assistant flow machinery (unlike the mixin unit
tests, which stub the coordinator). The Hydro-Québec API is never contacted:
validate_lieu_conso, search_lieux_conso and async_setup_entry are patched, and the lookup parsing tests answer through aioclient_mock, so no socket is opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hydropannes.config_flow import (
    AmbiguousAddress,
    CannotConnect,
    InvalidFormat,
    InvalidLieuConso,
    search_lieux_conso,
)
from custom_components.hydropannes.const import (
    CONF_CODE_POSTAL,
    CONF_LIEU_CONSO,
    CONF_NOM_LIEU,
    CONF_NUMERO_CIVIQUE,
    DOMAIN,
    SEARCH_URL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

_VALIDATE = "custom_components.hydropannes.config_flow.validate_lieu_conso"
_SETUP = "custom_components.hydropannes.async_setup_entry"
_SEARCH = "custom_components.hydropannes.config_flow.search_lieux_conso"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration during tests."""
    yield


async def _start(hass: HomeAssistant, path: str):
    """Open the setup flow and pick a path from its menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": path})


def _lieu(numero: str, appartement: str = "") -> dict:
    """Build one lookup result shaped like the API's answer."""
    rue = "67, place des Outaouais"
    return {
        "lieuConsommation": numero,
        "adresseFormateePourChoixRue": f"{rue}, L'Île-Perrot",
        "adresseFormateePourChoixAppartementFr": f"{appartement}-{rue}" if appartement else rue,
        "adresseCompleteFr": f"{rue}, L'Île-Perrot, Qc J7V&nbsp;8K8",
        "eligible": True,
    }


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """A valid number creates a config entry titled with the location name."""
    result = await _start(hass, "numero")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "numero"

    with (
        patch(_VALIDATE, return_value=None),
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Maison"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The supplied name becomes the entry title and is not copied into data.
    assert result["title"] == "Maison"
    assert result["data"] == {CONF_LIEU_CONSO: "0123456789"}
    assert CONF_NOM_LIEU not in result["data"]


async def test_user_flow_strips_whitespace(hass: HomeAssistant) -> None:
    """Leading/trailing whitespace on the number is stripped before storage."""
    result = await _start(hass, "numero")
    with (
        patch(_VALIDATE, return_value=None) as validate,
        patch(_SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "  0123456789  ", CONF_NOM_LIEU: "Maison"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LIEU_CONSO] == "0123456789"
    # validate_lieu_conso receives the already-stripped number.
    assert validate.call_args.args[1] == "0123456789"


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
    result = await _start(hass, "numero")
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
        data={CONF_LIEU_CONSO: "0123456789"},
        version=2,
    ).add_to_hass(hass)

    result = await _start(hass, "numero")
    with patch(_VALIDATE, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_LIEU_CONSO: "0123456789", CONF_NOM_LIEU: "Chalet"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_address_flow_single_match(hass: HomeAssistant) -> None:
    """One match skips the choice and suggests the street address as the name."""
    result = await _start(hass, "adresse")
    assert result["step_id"] == "adresse"

    with patch(_SEARCH, return_value=[_lieu("0502021502")]) as search:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CODE_POSTAL: "j7v8k8", CONF_NUMERO_CIVIQUE: " 67 "},
        )

    # The postal code reaches the lookup in the only form it accepts.
    assert search.call_args.args[1:] == ("J7V 8K8", "67", "")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "nom"
    assert result["description_placeholders"] == {
        "adresse": "67, place des Outaouais, L'Île-Perrot, Qc J7V 8K8",
        "lieu_consommation": "0502021502",
    }
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested == {CONF_NOM_LIEU: "67, place des Outaouais, L'Île-Perrot"}

    with patch(_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NOM_LIEU: "Maison"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maison"
    assert result["data"] == {CONF_LIEU_CONSO: "0502021502"}
    assert result["result"].unique_id == "0502021502"


async def test_address_flow_several_matches(hass: HomeAssistant) -> None:
    """Several matches show a choice list before naming."""
    result = await _start(hass, "adresse")
    with patch(_SEARCH, return_value=[_lieu("1111111111", "1"), _lieu("2222222222", "2")]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CODE_POSTAL: "J7V 8K8", CONF_NUMERO_CIVIQUE: "67"},
        )

    assert result["step_id"] == "choix"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LIEU_CONSO: "2222222222"}
    )
    assert result["step_id"] == "nom"

    with patch(_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NOM_LIEU: "Logement 2"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_LIEU_CONSO: "2222222222"}


@pytest.mark.parametrize(
    ("search", "code_postal", "expected"),
    [
        ({"return_value": []}, "J7V 8K8", {"base": "adresse_introuvable"}),
        ({"side_effect": AmbiguousAddress}, "J7V 8K8", {"base": "adresse_ambigue"}),
        ({"side_effect": CannotConnect}, "J7V 8K8", {"base": "cannot_connect"}),
        ({"return_value": []}, "J7V 8K", {CONF_CODE_POSTAL: "invalid_code_postal"}),
    ],
)
async def test_address_flow_errors(hass: HomeAssistant, search, code_postal, expected) -> None:
    """Each lookup failure re-shows the address form with the right error."""
    result = await _start(hass, "adresse")
    with patch(_SEARCH, **search):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CODE_POSTAL: code_postal, CONF_NUMERO_CIVIQUE: "67"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "adresse"
    assert result["errors"] == expected


async def test_address_flow_duplicate_aborts(hass: HomeAssistant) -> None:
    """A found number that is already configured aborts before asking for a name."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="0502021502",
        data={CONF_LIEU_CONSO: "0502021502"},
        version=2,
    ).add_to_hass(hass)

    result = await _start(hass, "adresse")
    with patch(_SEARCH, return_value=[_lieu("0502021502")]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CODE_POSTAL: "J7V 8K8", CONF_NUMERO_CIVIQUE: "67"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_search_lieux_conso_parses_answer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The lookup drops ineligible and duplicate locations and sends the address as query parameters."""
    aioclient_mock.get(
        SEARCH_URL,
        json=[
            _lieu("0502021502"),
            _lieu("0502021502"),
            {**_lieu("3333333333"), "eligible": False},
            {"lieuConsommation": "abc"},
        ],
    )

    lieux = await search_lieux_conso(hass, "J7V 8K8", "67", "")

    assert [lieu["lieuConsommation"] for lieu in lieux] == ["0502021502"]
    params = aioclient_mock.mock_calls[0][1].query
    assert params["codePostal"] == "J7V 8K8"
    assert params["numeroCivique"] == "67"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (400, {"error": {"code": "BSSP0001"}}, AmbiguousAddress),
        (400, {"error": {"code": "AUTRE"}}, CannotConnect),
        (500, {"error": {"code": "INTERNAL_SERVER_ERROR"}}, CannotConnect),
        (200, {"inattendu": True}, CannotConnect),
    ],
)
async def test_search_lieux_conso_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status, body, error
) -> None:
    """Error answers map to the exceptions the address step turns into form errors."""
    aioclient_mock.get(SEARCH_URL, status=status, json=body)

    with pytest.raises(error):
        await search_lieux_conso(hass, "J7V 8K8", "67", "")


async def test_reconfigure_updates_number(hass: HomeAssistant) -> None:
    """Reconfigure replaces the number and unique_id on the same entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="0123456789",
        data={CONF_LIEU_CONSO: "0123456789"},
        title="Maison",
        version=2,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with (
        patch(_VALIDATE, return_value=None),
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
    # The friendly name lives in the title and is untouched by reconfigure.
    assert entry.title == "Maison"


async def test_reconfigure_to_other_entry_number_aborts(hass: HomeAssistant) -> None:
    """Reconfiguring to a number owned by another entry is blocked."""
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1111111111",
        data={CONF_LIEU_CONSO: "1111111111"},
        version=2,
    )
    other.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="0123456789",
        data={CONF_LIEU_CONSO: "0123456789"},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    with patch(_VALIDATE, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LIEU_CONSO: "1111111111"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # Original entry is unchanged.
    assert entry.data[CONF_LIEU_CONSO] == "0123456789"
