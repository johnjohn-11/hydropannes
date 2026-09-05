"""Config flow for Hydro-Pannes integration.

Handles the initial user setup (lieu de consommation + friendly name) and
reconfiguration (change the number). The lieu de consommation number is
validated against the Hydro-Québec API before the entry is created so
configuration errors surface early.

There is no options flow: the location name is the config entry title, which
Home Assistant already lets the user change through the entry's own Rename
action. Keeping a second copy in ``entry.data`` only let the two drift apart.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .const import API_URL, CONF_LIEU_CONSO, CONF_NOM_LIEU, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Hydro-Québec lieu de consommation identifiers are always exactly 10 digits.
_LIEU_CONSO_RE = re.compile(r"^\d{10}$")

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIEU_CONSO): str,
        vol.Required(CONF_NOM_LIEU): vol.All(str, vol.Length(min=1)),
    }
)

# Reconfigure only changes the consumption location number; the name is the
# entry title and is changed with Home Assistant's own Rename action.
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


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Hydro-Pannes."""

    # Version 2 dropped the location name from entry.data; see
    # async_migrate_entry in __init__.py.
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the user-initiated setup step.

        Strips whitespace from the lieu de consommation number before
        validation and storage so that accidental leading/trailing spaces
        never end up in the config entry or in API URLs. The supplied name
        becomes the entry title and is not duplicated into entry.data.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            lieu = user_input[CONF_LIEU_CONSO].strip()
            try:
                await validate_lieu_conso(self.hass, lieu)
            except InvalidFormat:
                errors[CONF_LIEU_CONSO] = "invalid_format"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidLieuConso:
                errors["base"] = "invalid_lieu"
            except Exception:
                _LOGGER.exception("Unexpected exception in config flow")
                errors["base"] = "unknown"
            else:
                # Outside the try/except so the AbortFlow raised by
                # _abort_if_unique_id_configured propagates instead of being
                # swallowed by the catch-all above.
                await self.async_set_unique_id(lieu)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NOM_LIEU],
                    data={CONF_LIEU_CONSO: lieu},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
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
            try:
                await validate_lieu_conso(self.hass, lieu)
            except InvalidFormat:
                errors[CONF_LIEU_CONSO] = "invalid_format"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidLieuConso:
                errors["base"] = "invalid_lieu"
            except Exception:
                _LOGGER.exception("Unexpected exception in reconfigure flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(lieu)
                # Block adopting a number already configured on a different entry.
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.entry_id != reconfigure_entry.entry_id and entry.unique_id == lieu:
                        return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
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
