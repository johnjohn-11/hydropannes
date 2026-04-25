"""Config flow for Hydro-Pannes integration.

Handles the initial user setup (lieu de consommation + friendly name) and
the options flow for renaming an existing location.  The lieu de consommation
number is validated against the Hydro-Québec API before the entry is created
to surface configuration errors early.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant import config_entries
from homeassistant.core import callback
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


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the lieu de consommation by querying the Hydro-Québec API.

    Raises:
        InvalidFormat: The number does not match the 10-digit pattern.
        CannotConnect: A network error prevented the validation request.
        InvalidLieuConso: The API returned an empty payload for this number.

    Returns:
        A dict with the ``title`` key set to the user-supplied location name.

    """
    lieu_conso = data[CONF_LIEU_CONSO]  # already stripped by the caller

    if not _LIEU_CONSO_RE.match(lieu_conso):
        raise InvalidFormat

    url = API_URL.format(lieu_conso)
    session = async_get_clientsession(hass)

    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                raise CannotConnect
            json_data = await response.json()
            if not json_data:
                raise InvalidLieuConso
    except aiohttp.ClientError as err:
        _LOGGER.debug("HydroPannes config_flow network error: %s", err)
        raise CannotConnect from err

    return {"title": data[CONF_NOM_LIEU]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Hydro-Pannes."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow handler for renaming the location."""
        return OptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user-initiated setup step.

        Strips whitespace from the lieu de consommation number before
        validation and storage so that accidental leading/trailing spaces
        never end up in the config entry or in API URLs.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_LIEU_CONSO] = user_input[CONF_LIEU_CONSO].strip()
            try:
                info = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(user_input[CONF_LIEU_CONSO])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)
            except InvalidFormat:
                errors[CONF_LIEU_CONSO] = "invalid_format"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidLieuConso:
                errors["base"] = "invalid_lieu"
            except Exception:
                _LOGGER.exception("Unexpected exception in config flow")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for renaming a configured location.

    Changes are written back to ``entry.data`` (not ``entry.options``) so that
    the coordinator and all entities see the updated name immediately via the
    existing data path, without requiring a coordinator restart.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Present the rename form and apply the change when submitted."""
        if user_input is not None:
            new_data = {
                **self.config_entry.data,
                CONF_NOM_LIEU: user_input[CONF_NOM_LIEU],
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
                title=user_input[CONF_NOM_LIEU],
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NOM_LIEU,
                        default=self.config_entry.data.get(CONF_NOM_LIEU, ""),
                    ): vol.All(str, vol.Length(min=1)),
                }
            ),
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
