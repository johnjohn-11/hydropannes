# Hydro-Pannes

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/johnjohn-11/hydropannes.svg)](https://github.com/johnjohn-11/hydropannes/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.3%2B-blue.svg)](https://www.home-assistant.io/)

🇫🇷 [Version française](README.md)

Home Assistant integration that tracks Hydro-Québec service for one or more consumption locations: current outages, planned service interruptions and the estimated restoration time. It shows the same information as the [Info-pannes](https://pannes.hydroquebec.com/pannes/) site.

> ⚠️ **This integration is not affiliated with Hydro-Québec.** If something goes wrong, open an [issue on GitHub](https://github.com/johnjohn-11/hydropannes/issues). Do not contact Hydro-Québec customer service.

## Features

- 🔌 Current outages, major outages and gradual service restoration, as on Info-pannes
- 🔧 Intervention step, cause, addresses affected and estimated restoration time
- 📅 Planned service interruptions, also in a Home Assistant calendar
- 📍 Several locations, each with its own device
- ⚡ Polls every 60 seconds during an outage, every 3 minutes otherwise
- 🔔 `hydropannes_data_changed` event on every data change

## Installation

### HACS (recommended)

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=johnjohn-11&repository=hydropannes&category=integration)

Or in HACS: the 3 dots at the top right → **Custom repositories**, add `https://github.com/johnjohn-11/hydropannes` with the **Integration** category, install "Hydro-Pannes", then restart Home Assistant.

### Manual installation

Copy the `custom_components/hydropannes` folder of the latest [release](https://github.com/johnjohn-11/hydropannes/releases/latest) into `config/custom_components/`, then restart Home Assistant.

## Configuration

[![Add the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hydropannes)

Or **Settings** → **Devices & services** → **+ Add integration** → "Hydro-Pannes". Enter the **consumption location number** (10 digits, see the [domo-quebec guide](https://github.com/domo-quebec/domo-quebec/blob/main/hydro-quebec/configuration_info-panne.md) to find it) and a **name** ("Home", "Cottage"). Repeat for each location.

- **Rename a location**: the 3 dots next to the location → **Rename**. Existing entity IDs do not change.
- **Fix the number**: the 3 dots → **Reconfigure**. Entities and history are kept.

## Entities

Entity IDs follow the location name and the entity names in your Home Assistant language. The examples below use a location named `home` with Home Assistant in English.

| Entity | Description |
|--------|-------------|
| Outage info | Overall service status (see the states below) |
| Intervention status | Intervention step, with a `description` attribute |
| Restoration | Restoration step: being assessed, expected or under review |
| Cause | Cause of the outage, with `description` and `code_cause` attributes |
| Urgency level | Normal or major outage |
| Addresses affected | Number of addresses affected (`arrondi` attribute: the site's wording, such as "150 or less") |
| Start date | Start of the outage or interruption |
| End date | Actual or estimated end (`fin_estimee_min` attribute when Hydro-Québec gives a range) |
| Time until restoration | Time left until the estimated restoration |
| Duration | Outage duration in seconds |
| Last update | Last data update *(disabled by default)* |
| Service status (binary sensor) | `on` during an outage or a planned interruption under way |
| Planned intervention (binary sensor) | `on` when a planned interruption is upcoming or under way. Its attributes give `debut`, `fin`, `duree_prevue`, the fallback slot `report_debut` / `report_fin` shown as "In case of postponement", and `interruptions_suivantes` |
| Planned interruptions (calendar) | Planned interruptions that are not cancelled, shown in the Calendar panel |

The `description` and `arrondi` attribute texts follow the Home Assistant language (French or English).

### States

In automations, use the state (`states()`). The translated label comes from `state_translated()`. States are the same in every language.

**Outage info**: `aucune_panne`, `panne_en_cours`, `panne_majeure`, `reprise_graduelle`, `service_retabli`, `interruption_planifiee_en_cours`, `interruption_planifiee_a_venir`, `interruption_planifiee_terminee`, `interruption_planifiee_annulee`, `interruption_planifiee_reportee`. For a cancelled or postponed interruption, the `raison_annulation` attribute gives the reason.

**Intervention status**: `evaluation_travaux`, `equipe_designee`, `travaux_en_cours`, `travaux_par_priorite`, `retablissement_en_evaluation`, `retablissement_prevu`, `fin_non_determinee`, `reprise_graduelle`, `service_retabli`, `interruption_planifiee_a_venir`, `interruption_planifiee_reportee`, `interruption_planifiee_annulee`.

**Restoration**: `en_evaluation`, `prevu`, `en_revision`.

**Urgency level**: `normal`, `panne_majeure`.

**Cause**: one of the 23 Info-pannes causes, such as `foudre`, `vents_violents`, `dommages_vegetation` or `indeterminee`. The full list is in the entity's `options` attribute.

## Automation examples

### Notify on an outage

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.home_service_status
    to: "on"
actions:
  - action: notify.mobile_app
    data:
      title: "⚡ Power outage"
      message: >
        Cause: {{ state_translated('sensor.home_cause') }}.
        Estimated restoration: {{ states('sensor.home_end_date') }}.
```

### Reminder the day before a planned interruption

```yaml
triggers:
  - trigger: calendar
    event: start
    offset: "-12:00:00"
    entity_id: calendar.home_planned_interruptions
actions:
  - action: notify.mobile_app
    data:
      title: "📅 Planned interruption tomorrow"
      message: >
        From {{ as_timestamp(trigger.calendar_event.start) | timestamp_custom('%H:%M') }}
        to {{ as_timestamp(trigger.calendar_event.end) | timestamp_custom('%H:%M') }}.
```

## `hydropannes_data_changed` event

Fired whenever a location's data changes, with `entry_id`, `lieu_consommation`, `timestamp` and the full payload in `data`. Useful to log changes. The first poll after a start fires nothing.

## Troubleshooting

- **The number is rejected**: it must have exactly 10 digits.
- **Entities are unavailable**: the Hydro-Québec API does not answer or answered in an unexpected format. The error message is in the logs, and a card appears in **Repairs** if the API structure changed.
- **Report a problem**: attach the diagnostics report (the location's 3 dots → **Download diagnostics**, the location number is masked in it) to an [issue](https://github.com/johnjohn-11/hydropannes/issues).

## Credits

Data provided by [Hydro-Québec](https://www.hydroquebec.com/) through the public Info-pannes API. Thanks to [@nxor](https://github.com/nxor) and [@MivraMe](https://github.com/MivraMe), whose template-sensor solution inspired this integration.

MIT license, see [LICENSE](LICENSE). Contributions are welcome through issues or pull requests.
