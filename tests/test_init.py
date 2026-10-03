"""Integration setup/unload tests using pytest-homeassistant-custom-component.

The Hydro-Québec API is served by aioclient_mock, so the coordinator's first refresh runs against a stubbed response and no real socket is opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hydropannes.const import (
    API_URL,
    CAUSE_DESCRIPTIONS,
    CAUSE_DESCRIPTIONS_EN,
    CONF_LIEU_CONSO,
    CONF_NOM_LIEU,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

LIEU = "0123456789"
PAYLOAD = [{"etat": "A", "idLieuConso": LIEU, "interruptions": []}]


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration during tests."""
    yield


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=LIEU,
        data={CONF_LIEU_CONSO: LIEU, CONF_NOM_LIEU: "Maison"},
        title="Maison",
    )


async def test_setup_and_unload(hass: HomeAssistant, aioclient_mock) -> None:
    """A successful first refresh loads the entry, entities, then unloads."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data["idLieuConso"] == LIEU
    # Sensor and binary_sensor entities were created for this location.
    assert hass.states.async_entity_ids()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_unique_ids_are_stable(hass: HomeAssistant, aioclient_mock) -> None:
    """Every entity keeps the unique_id it was registered with; a change would orphan it."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registered = {
        (e.domain, e.unique_id.removeprefix(f"{entry.entry_id}_"))
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert registered == {
        ("sensor", "info_pannes"),
        ("sensor", "niveau_urgence"),
        ("sensor", "nbclient"),
        ("sensor", "date_debut"),
        ("sensor", "datefin"),
        ("sensor", "statut_intervention"),
        ("sensor", "retablissement"),
        ("sensor", "cause"),
        ("sensor", "duree"),
        ("sensor", "delai_avant_retablissement"),
        ("sensor", "derniere_maj"),
        ("sensor", "idlieuconso"),
        ("binary_sensor", "etat_service"),
        ("binary_sensor", "intervention_planifiee"),
        ("calendar", "calendrier"),
    }


async def test_enum_sensor_states_accepted_by_home_assistant(
    hass: HomeAssistant, aioclient_mock, caplog
) -> None:
    """Enum sensors expose slugs that Home Assistant accepts as valid states.

    Home Assistant rejects any state outside a sensor's ``options`` and logs an error, so this drives the real state machine rather than the sensor classes alone.
    """
    hass.config.language = "fr"
    outage = [
        {
            "etat": "N",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "dateDebut": "2024-01-01T00:00:00-05:00",
                    "interruptionPlanifiee": False,
                    "niveauUrgence": "P",
                    "codeCause": "11",
                    "codeIntervention": "L",
                }
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=outage)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Entity ids follow the translated name, so resolve them by unique_id.
    registry = er.async_get(hass)

    def entity_id_for(key: str) -> str:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        assert entity_id is not None, f"no sensor registered for {key}"
        return entity_id

    def state_of(key: str) -> str:
        return hass.states.get(entity_id_for(key)).state

    assert state_of("info_pannes") == "panne_majeure"
    assert state_of("niveau_urgence") == "panne_majeure"
    assert state_of("cause") == "defaillance_equipement"
    assert state_of("statut_intervention") == "travaux_par_priorite"
    # No estimated end while the crew is on site: the site shows the time as being revised.
    assert state_of("retablissement") == "en_revision"

    # The raw HQ code survives as an attribute of the cause sensor.
    cause_state = hass.states.get(entity_id_for("cause"))
    assert cause_state.attributes["code_cause"] == "11"
    assert cause_state.attributes["description"] == CAUSE_DESCRIPTIONS["defaillance_equipement"]
    # Home Assistant advertises the declared options on the entity.
    assert "bris_equipement" in cause_state.attributes["options"]

    # No "provides invalid state" / options complaint from the sensor platform.
    assert "invalid" not in caplog.text.lower()


async def test_setup_retry_on_api_error(hass: HomeAssistant, aioclient_mock) -> None:
    """A persistent 5xx leaves the entry in SETUP_RETRY (ConfigEntryNotReady)."""
    aioclient_mock.get(API_URL.format(LIEU), status=500)
    entry = _entry()
    entry.add_to_hass(hass)

    # Zero the coordinator's inter-retry backoff to keep the test fast.
    with patch("custom_components.hydropannes.coordinator.RETRY_DELAY", 0):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_api_schema_issue_created_and_cleared(hass: HomeAssistant, aioclient_mock) -> None:
    """A missing root field raises a repair issue; recovery clears it."""
    # First response drops required root fields (idLieuConso, interruptions).
    aioclient_mock.get(API_URL.format(LIEU), json=[{"etat": "A"}])
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    issue_id = f"api_incompatible_{entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    # A well-formed response on the next refresh clears the issue.
    aioclient_mock.clear_requests()
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_device_is_named_after_the_location_alone(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """The device name does not repeat the integration name.

    With has_entity_name the device name prefixes every entity name, and Home Assistant already shows "Hydro-Pannes" around the device, so "HydroPannes Maison Info-pannes" said it twice.
    """
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Maison"


async def test_rename_without_options_flow(hass: HomeAssistant, aioclient_mock) -> None:
    """Renaming the entry renames the device, with no options flow involved.

    The options flow that used to do this duplicated Home Assistant's own Rename action, so it was removed; this proves renaming still works.
    """
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The integration no longer advertises an options flow.
    assert entry.supports_options is False

    hass.config_entries.async_update_entry(entry, title="Chalet")
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.name == "Chalet"


async def test_migration_v1_drops_stored_name(hass: HomeAssistant, aioclient_mock) -> None:
    """A version 1 entry loses its duplicated name but keeps its title."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LIEU,
        data={CONF_LIEU_CONSO: LIEU, CONF_NOM_LIEU: "Maison"},
        title="Maison",
        version=1,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert CONF_NOM_LIEU not in entry.data
    assert entry.data[CONF_LIEU_CONSO] == LIEU
    # The name survives as the title, which is what names the device.
    assert entry.title == "Maison"


async def test_migration_2_1_drops_leftover_options(hass: HomeAssistant, aioclient_mock) -> None:
    """Options left behind by the removed options flow are cleared."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LIEU,
        data={CONF_LIEU_CONSO: LIEU},
        options={"json_log": True},
        title="Maison",
        version=2,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (entry.version, entry.minor_version) == (2, 2)
    assert entry.options == {}
    assert entry.data == {CONF_LIEU_CONSO: LIEU}


async def test_reconfigure_reloads_once_through_the_listener(
    hass: HomeAssistant, aioclient_mock, caplog
) -> None:
    """Reconfiguring a loaded entry reloads it without Home Assistant's double-reload report."""
    other = "9876543210"
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    aioclient_mock.get(
        API_URL.format(other), json=[{"etat": "A", "idLieuConso": other, "interruptions": []}]
    )
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    with patch("custom_components.hydropannes.config_flow.validate_lieu_conso"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_LIEU_CONSO: other}
        )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.state is ConfigEntryState.LOADED
    # The reload rebuilt the coordinator for the new number.
    assert entry.runtime_data.lieu_conso == other
    # One setup, hence one first refresh, for the new number: a second reload would fetch it twice.
    assert sum(str(url).endswith(other) for _, url, *_ in aioclient_mock.mock_calls) == 1
    assert "should use it for scheduling a reload" not in caplog.text


async def test_broken_payload_raises_a_repair_issue(hass: HomeAssistant, aioclient_mock) -> None:
    """A payload that is not a list raises a repair issue, the entities go unavailable, and a valid payload clears it."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.get(API_URL.format(LIEU), json={"not": "a list"})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    issue_registry = ir.async_get(hass)
    issue_id = f"api_invalid_response_{entry.entry_id}"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
    assert _state(hass, entry, "sensor", "info_pannes").state == "unavailable"

    aioclient_mock.clear_requests()
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_removed_entities_leave_the_registry(hass: HomeAssistant, aioclient_mock) -> None:
    """The API-compatibility entity of an older version is removed at setup, the consumption location is kept."""
    aioclient_mock.get(API_URL.format(LIEU), json=PAYLOAD)
    entry = _entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for domain, suffix in (("sensor", "idlieuconso"), ("binary_sensor", "api_compatibility")):
        registry.async_get_or_create(
            domain, DOMAIN, f"{entry.entry_id}_{suffix}", config_entry=entry
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_idlieuconso") is not None
    )
    assert (
        registry.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_api_compatibility")
        is None
    )


async def test_calendar_lists_planned_interruptions(hass: HomeAssistant, aioclient_mock) -> None:
    """The calendar shows the effective window of each planned interruption that is not cancelled."""
    hass.config.language = "fr"
    payload = [
        {
            "etat": "A",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "idInterruption": {
                        "site": "ORL",
                        "typeObjet": "A",
                        "noInterruption": 1,
                        "noSection": 1,
                    },
                    "dateDebut": "2099-10-05T13:00:00.000+00:00",
                    "dateFin": "2099-10-05T19:00:00.000+00:00",
                    "dateDebutReport": "2099-10-13T13:00:00.000+00:00",
                    "dateFinReport": "2099-10-13T19:00:00.000+00:00",
                    "etat": "P",
                    "dureePrevu": 360,
                    "interruptionPlanifiee": True,
                },
                {
                    "idInterruption": {
                        "site": "ORL",
                        "typeObjet": "A",
                        "noInterruption": 2,
                        "noSection": 1,
                    },
                    "dateDebut": "2099-11-05T13:00:00.000+00:00",
                    "dateFin": "2099-11-05T19:00:00.000+00:00",
                    "etat": "A",
                    "interruptionPlanifiee": True,
                },
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=payload)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = _state(hass, entry, "calendar", "calendrier")
    assert state.state == "off"
    assert state.attributes["start_time"].startswith("2099-10-05")
    assert state.attributes["message"] == "Interruption planifiée"
    assert "En cas de report" in state.attributes["description"]

    calendar = hass.data["calendar"].get_entity(state.entity_id)
    events = await calendar.async_get_events(
        hass,
        dt_util.parse_datetime("2099-01-01T00:00:00+00:00"),
        dt_util.parse_datetime("2100-01-01T00:00:00+00:00"),
    )
    assert [e.uid for e in events] == ["ORL-A-1-1"]


def _state(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, f"no {domain} registered for {key}"
    return hass.states.get(entity_id)


async def test_attribute_texts_follow_the_configured_language(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Attribute texts are in English when Home Assistant is not configured in French."""
    hass.config.language = "en"
    outage = [
        {
            "etat": "N",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "dateDebut": "2024-01-01T00:00:00-05:00",
                    "etat": "C",
                    "interruptionPlanifiee": False,
                    "codeCause": "11",
                    "codeIntervention": "N",
                    "nbClient": 120,
                }
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=outage)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    cause = _state(hass, entry, "sensor", "cause")
    assert cause.attributes["description"] == CAUSE_DESCRIPTIONS_EN["defaillance_equipement"]
    assert _state(hass, entry, "sensor", "nbclient").attributes["arrondi"] == "150 or less"


async def test_disagreeing_root_shows_an_outage_without_details(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Through the real update cycle: root etat "A" with an unplanned interruption under way."""
    payload = [
        {
            "etat": "A",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "dateDebut": "2024-01-01T00:00:00-05:00",
                    "etat": "C",
                    "interruptionPlanifiee": False,
                    "codeIntervention": "N",
                }
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=payload)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, entry, "sensor", "info_pannes").state == "panne_en_cours"
    assert _state(hass, entry, "binary_sensor", "etat_service").state == "on"
    assert _state(hass, entry, "sensor", "statut_intervention").state == "unknown"


async def test_planned_attributes_through_home_assistant(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Through the real update cycle: a confirmed planned interruption exposes its fallback slot."""
    payload = [
        {
            "etat": "A",
            "idLieuConso": LIEU,
            "interruptions": [
                {
                    "dateDebut": "2099-10-05T13:00:00.000+00:00",
                    "dateFin": "2099-10-05T19:00:00.000+00:00",
                    "dateDebutReport": "2099-10-13T13:00:00.000+00:00",
                    "dateFinReport": "2099-10-13T19:00:00.000+00:00",
                    "etat": "P",
                    "dureePrevu": 360,
                    "interruptionPlanifiee": True,
                }
            ],
        }
    ]
    aioclient_mock.get(API_URL.format(LIEU), json=payload)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    planned = _state(hass, entry, "binary_sensor", "intervention_planifiee")
    assert planned.state == "on"
    assert planned.attributes["duree_prevue"] == 360
    assert planned.attributes["report_debut"].startswith("2099-10-13")
    assert "fin_au_plus_tard" not in planned.attributes
