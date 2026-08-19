"""Config flow for Hydro-Pannes integration.

Handles the initial user setup (lieu de consommation + friendly name) and
the options flow (rename + JSONL change-log opt-in).  The lieu de
consommation number is validated against the Hydro-Québec API before the
entry is created to surface configuration errors early.
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

from .const import API_URL, CONF_JSON_LOG, CONF_LIEU_CONSO, CONF_NOM_LIEU, DOMAIN

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

# Reconfigure only changes the consumption location number; the friendly name
# is edited through the options flow.
STEP_RECONFIGURE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIEU_CONSO): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the lieu de consommation by querying the Hydro-Québec API.

    Raises:
        InvalidFormat: The number does not match the 10-digit pattern.
        CannotConnect: A network error or timeout prevented the validation request.
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

    return {"title": data[CONF_NOM_LIEU]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow for Hydro-Pannes."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow handler."""
        return OptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                await self.async_set_unique_id(user_input[CONF_LIEU_CONSO])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

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
            # validate_input needs a name for its return value; reuse the
            # existing one since reconfigure does not change it.
            validate_data = {
                CONF_LIEU_CONSO: lieu,
                CONF_NOM_LIEU: reconfigure_entry.data[CONF_NOM_LIEU],
            }
            try:
                await validate_input(self.hass, validate_data)
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


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow: rename the location and toggle the JSONL log.

    The name is written back to ``entry.data`` and the entry title; the
    JSONL toggle is stored in ``entry.options``.  Everything is applied in a
    single ``async_update_entry`` call so the update listener (which reloads
    the entry) fires only once.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Present the options form and apply the changes when submitted."""
        if user_input is not None:
            new_data = {
                **self.config_entry.data,
                CONF_NOM_LIEU: user_input[CONF_NOM_LIEU],
            }
            new_options = {
                **self.config_entry.options,
                CONF_JSON_LOG: user_input[CONF_JSON_LOG],
            }
            # Apply data, title, and options in one shot → one reload.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
                title=user_input[CONF_NOM_LIEU],
                options=new_options,
            )
            # data is identical to entry.options at this point, so this does
            # not trigger a second update event.
            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NOM_LIEU,
                        default=self.config_entry.data.get(CONF_NOM_LIEU, ""),
                    ): vol.All(str, vol.Length(min=1)),
                    vol.Required(
                        CONF_JSON_LOG,
                        default=self.config_entry.options.get(CONF_JSON_LOG, False),
                    ): bool,
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
