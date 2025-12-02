"""Config flow for Hydro-Pannes integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_URL, CONF_LIEU_CONSO, CONF_NOM_LIEU, DOMAIN

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
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                raise CannotConnect
            json_data = await response.json()
            if not json_data or len(json_data) == 0:
                raise InvalidLieuConso
    except aiohttp.ClientError as err:
        _LOGGER.debug("HydroPannes config_flow network error: %s", err)
        raise CannotConnect from err

    return {"title": data[CONF_NOM_LIEU]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hydro-Pannes."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
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

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Hydro-Pannes."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update the config entry data with new nom_lieu
            new_data = {**self.config_entry.data, CONF_NOM_LIEU: user_input[CONF_NOM_LIEU]}
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
                    ): str,
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidLieuConso(HomeAssistantError):
    """Error to indicate the provided lieu de consommation is invalid."""
