"""Config flow for Hydro-Pannes integration.

Handles the initial user setup and reconfiguration (change the number). Setup offers two paths: look the lieu de consommation up from a postal code and civic number, or type the number directly. A typed number is validated against the Hydro-Québec API before the entry is created so configuration errors surface early.

There is no options flow: the location name is the config entry title, which Home Assistant already lets the user change through the entry's own Rename action. Keeping a second copy in ``entry.data`` only let the two drift apart.
"""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import (
    API_URL,
    CONF_APPARTEMENT,
    CONF_CODE_POSTAL,
    CONF_LIEU_CONSO,
    CONF_NOM_LIEU,
    CONF_NUMERO_CIVIQUE,
    DOMAIN,
    SEARCH_URL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Hydro-Québec lieu de consommation identifiers are always exactly 10 digits.
_LIEU_CONSO_RE = re.compile(r"^\d{10}$")

_CODE_POSTAL_RE = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$")

# Error code the lookup returns with HTTP 400 when one address maps to several locations it cannot tell apart.
_SEARCH_DUPLICATES_CODE = "BSSP0001"

STEP_NUMERO_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIEU_CONSO): str,
        vol.Required(CONF_NOM_LIEU): vol.All(str, vol.Length(min=1)),
    }
)

STEP_ADRESSE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CODE_POSTAL): str,
        vol.Required(CONF_NUMERO_CIVIQUE): str,
        vol.Optional(CONF_APPARTEMENT): str,
    }
)

STEP_NOM_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NOM_LIEU): vol.All(str, vol.Length(min=1)),
    }
)

# Reconfigure only changes the consumption location number; the name is the entry title and is changed with Home Assistant's own Rename action.
STEP_RECONFIGURE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIEU_CONSO): str,
    }
)


async def validate_lieu_conso(hass: HomeAssistant, lieu_conso: str) -> None:
    """Validate a lieu de consommation number against the Hydro-Québec API.

    Args:
        hass: The Home Assistant instance.
        lieu_conso: The number to validate, already stripped by the caller.

    Raises:
        InvalidFormat: The number does not match the 10-digit pattern.
        CannotConnect: A network error or timeout prevented the validation request.
        InvalidLieuConso: The API returned an empty payload for this number.

    """
    if not _LIEU_CONSO_RE.match(lieu_conso):
        raise InvalidFormat

    url = API_URL.format(lieu_conso)
    session = async_get_clientsession(hass)

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                raise CannotConnect
            json_data = await response.json()
            if not json_data:
                raise InvalidLieuConso
    except (TimeoutError, aiohttp.ClientError) as err:
        # aiohttp total timeouts raise asyncio.TimeoutError, which is NOT a
        # ClientError subclass — both must be mapped to "cannot_connect".
        _LOGGER.debug("HydroPannes config_flow network error: %s", err)
        raise CannotConnect from err


def normalize_code_postal(code_postal: str) -> str:
    """Return a postal code as ``A1A 1A1``, the only form the lookup accepts.

    Without the space the lookup answers HTTP 500.

    Raises:
        InvalidCodePostal: The input is not a Canadian postal code.

    """
    compact = re.sub(r"\s", "", code_postal).upper()
    if not _CODE_POSTAL_RE.match(compact):
        raise InvalidCodePostal
    return f"{compact[:3]} {compact[3:]}"


async def search_lieux_conso(
    hass: HomeAssistant, code_postal: str, numero_civique: str, appartement: str
) -> list[dict[str, Any]]:
    """Look up the consumption locations at an address.

    Args:
        hass: The Home Assistant instance.
        code_postal: Postal code already normalized to ``A1A 1A1``.
        numero_civique: Civic number, already stripped.
        appartement: Apartment number, empty when there is none.

    Returns:
        The eligible locations found, one per distinct number, possibly empty.

    Raises:
        CannotConnect: A network error, a timeout or an unexpected answer.
        AmbiguousAddress: The API found several locations it cannot tell apart.

    """
    params = {
        "codePostal": code_postal,
        "numeroAppartement": appartement,
        "numeroCivique": numero_civique,
        "nomRue": "",
    }
    session = async_get_clientsession(hass)

    try:
        async with session.get(
            SEARCH_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 400:
                body = await response.json(content_type=None)
                error = body.get("error") if isinstance(body, dict) else None
                if isinstance(error, dict) and error.get("code") == _SEARCH_DUPLICATES_CODE:
                    raise AmbiguousAddress
                raise CannotConnect
            if response.status != 200:
                raise CannotConnect
            json_data = await response.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("HydroPannes address lookup error: %s", err)
        raise CannotConnect from err

    if not isinstance(json_data, list):
        raise CannotConnect

    lieux: dict[str, dict[str, Any]] = {}
    for item in json_data:
        if not isinstance(item, dict) or item.get("eligible") is False:
            continue
        numero = item.get("lieuConsommation")
        if isinstance(numero, str) and _LIEU_CONSO_RE.match(numero):
            lieux.setdefault(numero, item)
    return list(lieux.values())


def _format_adresse(lieu: dict[str, Any], key: str) -> str:
    """Return one of the lookup's address fields as plain text, empty when missing."""
    # The API embeds HTML entities such as &nbsp; in its formatted addresses.
    return html.unescape(str(lieu.get(key) or "")).replace("\xa0", " ").strip()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Hydro-Pannes."""

    # Version 2 dropped the location name from entry.data, 2.2 the leftover options; see async_migrate_entry in __init__.py.
    VERSION = 2
    MINOR_VERSION = 2

    async def _async_validate(self, lieu: str) -> dict[str, str]:
        """Validate a number and return the form errors, empty when it is valid.

        The unique-id checks stay in the callers, outside the catch-all below, so the AbortFlow they raise is not turned into an "unknown" error.
        """
        try:
            await validate_lieu_conso(self.hass, lieu)
        except InvalidFormat:
            return {CONF_LIEU_CONSO: "invalid_format"}
        except CannotConnect:
            return {"base": "cannot_connect"}
        except InvalidLieuConso:
            return {"base": "invalid_lieu"}
        except Exception:
            _LOGGER.exception("Unexpected exception while validating the consumption location")
            return {"base": "unknown"}
        return {}

    def __init__(self) -> None:
        """Initialize the flow state shared between the address steps."""
        self._lieux: dict[str, dict[str, Any]] = {}
        self._lieu: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user find the location by address or type its number."""
        return self.async_show_menu(step_id="user", menu_options=["adresse", "numero"])

    async def async_step_adresse(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Look the consumption location up from a postal code and civic number.

        The street name is not asked: the lookup returned the same result with or without it. One match goes straight to naming, several go to a choice list.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                lieux = await search_lieux_conso(
                    self.hass,
                    normalize_code_postal(user_input[CONF_CODE_POSTAL]),
                    user_input[CONF_NUMERO_CIVIQUE].strip(),
                    user_input.get(CONF_APPARTEMENT, "").strip(),
                )
            except InvalidCodePostal:
                errors = {CONF_CODE_POSTAL: "invalid_code_postal"}
            except CannotConnect:
                errors = {"base": "cannot_connect"}
            except AmbiguousAddress:
                errors = {"base": "adresse_ambigue"}
            except Exception:
                _LOGGER.exception("Unexpected exception while looking up the address")
                errors = {"base": "unknown"}
            else:
                if not lieux:
                    errors = {"base": "adresse_introuvable"}
                elif len(lieux) == 1:
                    return await self._async_select_lieu(lieux[0])
                else:
                    self._lieux = {lieu["lieuConsommation"]: lieu for lieu in lieux}
                    return await self.async_step_choix()

        return self.async_show_form(
            step_id="adresse",
            data_schema=self.add_suggested_values_to_schema(
                STEP_ADRESSE_DATA_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_choix(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick one location when the address has several, such as apartments."""
        if user_input is not None:
            return await self._async_select_lieu(self._lieux[user_input[CONF_LIEU_CONSO]])

        options = [
            SelectOptionDict(
                value=numero,
                label=f"{_format_adresse(lieu, 'adresseFormateePourChoixAppartementFr') or _format_adresse(lieu, 'adresseCompleteFr')} ({numero})",
            )
            for numero, lieu in self._lieux.items()
        ]
        return self.async_show_form(
            step_id="choix",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LIEU_CONSO): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def _async_select_lieu(self, lieu: dict[str, Any]) -> ConfigFlowResult:
        """Claim the found number, aborting when it is already configured, then ask for a name."""
        await self.async_set_unique_id(lieu["lieuConsommation"])
        self._abort_if_unique_id_configured()
        self._lieu = lieu
        return await self.async_step_nom()

    async def async_step_nom(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Name the location found by address, suggesting its street address."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NOM_LIEU],
                data={CONF_LIEU_CONSO: self._lieu["lieuConsommation"]},
            )

        return self.async_show_form(
            step_id="nom",
            data_schema=self.add_suggested_values_to_schema(
                STEP_NOM_DATA_SCHEMA,
                {CONF_NOM_LIEU: _format_adresse(self._lieu, "adresseFormateePourChoixRue")},
            ),
            description_placeholders={
                "adresse": _format_adresse(self._lieu, "adresseCompleteFr"),
                "lieu_consommation": self._lieu["lieuConsommation"],
            },
        )

    async def async_step_numero(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set the location up from a typed number.

        Strips whitespace from the lieu de consommation number before
        validation and storage so that accidental leading/trailing spaces
        never end up in the config entry or in API URLs. The supplied name becomes the entry title and is not duplicated into entry.data.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            lieu = user_input[CONF_LIEU_CONSO].strip()
            errors = await self._async_validate(lieu)
            if not errors:
                await self.async_set_unique_id(lieu)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NOM_LIEU],
                    data={CONF_LIEU_CONSO: lieu},
                )

        return self.async_show_form(
            step_id="numero", data_schema=STEP_NUMERO_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing location's number.

        Lets the user correct the lieu de consommation number in place —
        keeping the entry, its device and entity IDs, and its history — instead
        of deleting and re-adding. The number is the entry's unique ID, so it
        is re-validated and the unique ID is updated; adopting a number already
        used by another entry is blocked.
        """
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            lieu = user_input[CONF_LIEU_CONSO].strip()
            errors = await self._async_validate(lieu)
            if not errors:
                await self.async_set_unique_id(lieu)
                # Block adopting a number already configured on a different entry.
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.entry_id != reconfigure_entry.entry_id and entry.unique_id == lieu:
                        return self.async_abort(reason="already_configured")
                # The update listener reloads the entry when the data changes. Home Assistant reports a flow that also schedules its own reload for an entry with a listener.
                return self.async_update_and_abort(
                    reconfigure_entry,
                    unique_id=lieu,
                    data_updates={CONF_LIEU_CONSO: lieu},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_RECONFIGURE_DATA_SCHEMA,
                {CONF_LIEU_CONSO: reconfigure_entry.data[CONF_LIEU_CONSO]},
            ),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class CannotConnect(HomeAssistantError):
    """Raised when the Hydro-Québec API is unreachable."""


class InvalidLieuConso(HomeAssistantError):
    """Raised when the API returns an empty payload for the supplied number."""


class InvalidFormat(HomeAssistantError):
    """Raised when the lieu de consommation number is not exactly 10 digits."""


class InvalidCodePostal(HomeAssistantError):
    """Raised when the postal code is not in the Canadian A1A 1A1 form."""


class AmbiguousAddress(HomeAssistantError):
    """Raised when the lookup finds several locations it cannot tell apart."""
