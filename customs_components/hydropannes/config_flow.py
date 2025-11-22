"""Config flow for Hydro-Pannes integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_LIEU_CONSO, CONF_NOM_LIEU, API_URL

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIEU_CONSO): str,
        vol.Required(CONF_NOM_LIEU): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    lieu_conso = data[CONF_LIEU_CONSO]
    url = API_URL.format(lieu_conso)
    session = async_get_clientsession(hass)

    try:
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                raise CannotConnect
            json_data = await response.json()
            if not json_data or len(json_data) == 0:
                raise InvalidLieuConso
    except aiohttp.ClientError as err:
        _LOGGER.debug("HydroPannes config_flow network error: %s", err)
        raise CannotConnect

    return {"title": data[CONF_NOM_LIEU]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hydro-Pannes."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(user_input[CONF_LIEU_CONSO])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidLieuConso:
                errors["base"] = "invalid_lieu"
            except Exception:
                _LOGGER.exception("Unexpected exception in config flow")
                errors["base"] = "unknown"

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidLieuConso(HomeAssistantError):
    """Error to indicate the provided lieu de consommation is invalid."""
