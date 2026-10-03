# Hydro-Pannes

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/johnjohn-11/hydropannes.svg)](https://github.com/johnjohn-11/hydropannes/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.3%2B-blue.svg)](https://www.home-assistant.io/)

🇬🇧 [English version](README.en.md)

Intégration Home Assistant qui suit l'état du service d'Hydro-Québec pour un ou plusieurs lieux de consommation : pannes en cours, interruptions planifiées et estimation du rétablissement. Elle affiche la même chose que le site [Info-pannes](https://pannes.hydroquebec.com/pannes/).

> ⚠️ **Cette intégration n'est pas affiliée à Hydro-Québec.** En cas de problème, ouvrez une [issue sur GitHub](https://github.com/johnjohn-11/hydropannes/issues). Ne contactez pas le service à la clientèle d'Hydro-Québec.

## Fonctionnalités

- 🔌 Pannes en cours, panne majeure et rétablissement graduel, comme sur Info-pannes
- 🔧 Étape de l'intervention, cause, adresses touchées et heure de rétablissement estimée
- 📅 Interruptions planifiées, aussi dans un calendrier Home Assistant
- 📍 Plusieurs lieux, chacun avec son propre appareil
- ⚡ Relevé toutes les 60 secondes pendant une panne, toutes les 3 minutes sinon
- 🔔 Événement `hydropannes_data_changed` à chaque changement des données

## Installation

### HACS (recommandé)

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=johnjohn-11&repository=hydropannes&category=integration)

Ou dans HACS : les 3 points en haut à droite → **Dépôts personnalisés**, ajouter `https://github.com/johnjohn-11/hydropannes` avec la catégorie **Intégration**, installer « Hydro-Pannes », puis redémarrer Home Assistant.

### Installation manuelle

Copier le dossier `custom_components/hydropannes` de la dernière [release](https://github.com/johnjohn-11/hydropannes/releases/latest) dans `config/custom_components/`, puis redémarrer Home Assistant.

## Configuration

[![Ajouter l'intégration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hydropannes)

Ou **Paramètres** → **Appareils et services** → **+ Ajouter une intégration** → « Hydro-Pannes ». Deux façons de trouver le lieu :

- **Rechercher par adresse** : code postal, numéro civique et, s'il y a lieu, appartement. Si plusieurs lieux correspondent, choisir le bon dans la liste. L'adresse sert seulement à trouver le numéro et n'est pas conservée.
- **Entrer le numéro** : le numéro de lieu de consommation à 10 chiffres (voir le [guide domo-quebec](https://github.com/domo-quebec/domo-quebec/blob/main/hydro-quebec/configuration_info-panne.md) pour le trouver).

Donner ensuite un **nom** au lieu (« Maison », « Chalet »). Répéter pour chaque lieu.

- **Renommer un lieu** : les 3 points à côté du lieu → **Renommer**. Les `entity_id` existants ne changent pas.
- **Corriger le numéro** : les 3 points → **Reconfigurer**. Les entités et l'historique sont conservés.

## Entités

Dans les exemples, `maison` est le nom donné au lieu.

| Entité | Description |
|--------|-------------|
| `sensor.maison_info_pannes` | État général du service (voir les états ci-dessous) |
| `sensor.maison_statut_intervention` | Étape de l'intervention, avec un attribut `description` |
| `sensor.maison_retablissement` | Étape du rétablissement : en évaluation, prévu ou en révision |
| `sensor.maison_cause` | Cause de la panne, avec les attributs `description` et `code_cause` |
| `sensor.maison_niveau_urgence` | Normal ou panne majeure |
| `sensor.maison_adresses_touchees` | Nombre d'adresses touchées (attribut `arrondi` : le libellé du site, par exemple « 150 ou moins ») |
| `sensor.maison_date_debut` | Début de la panne ou de l'interruption |
| `sensor.maison_date_fin` | Fin réelle ou estimée (attribut `fin_estimee_min` quand Hydro-Québec donne une fourchette) |
| `sensor.maison_delai_avant_retablissement` | Temps restant avant le rétablissement estimé |
| `sensor.maison_duree` | Durée de la panne en secondes |
| `sensor.maison_derniere_maj` | Dernière mise à jour des données *(désactivé par défaut)* |
| `sensor.maison_lieu_consommation` | Numéro de lieu de consommation, pour distinguer les lieux dans les journaux *(diagnostic, désactivé par défaut)* |
| `binary_sensor.maison_etat_du_service` | `on` pendant une panne ou une interruption planifiée en cours |
| `binary_sensor.maison_intervention_planifiee` | `on` quand une interruption planifiée est à venir ou en cours. Ses attributs donnent `debut`, `fin`, `duree_prevue`, le créneau `report_debut` / `report_fin` affiché « En cas de report », et `interruptions_suivantes` |
| `calendar.maison_interruptions_planifiees` | Les interruptions planifiées non annulées, visibles dans le panneau Calendrier |

Les textes des attributs `description` et `arrondi` suivent la langue de Home Assistant (français ou anglais).

### États

Dans une automatisation, utilisez l'état (`states()`). Le libellé traduit s'obtient avec `state_translated()`.

**`info_pannes`** : `aucune_panne`, `panne_en_cours`, `panne_majeure`, `reprise_graduelle`, `service_retabli`, `interruption_planifiee_en_cours`, `interruption_planifiee_a_venir`, `interruption_planifiee_terminee`, `interruption_planifiee_annulee`, `interruption_planifiee_reportee`. Pour une interruption annulée ou reportée, l'attribut `raison_annulation` donne la raison.

**`statut_intervention`** : `evaluation_travaux`, `equipe_designee`, `travaux_en_cours`, `travaux_par_priorite`, `retablissement_en_evaluation`, `retablissement_prevu`, `fin_non_determinee`, `reprise_graduelle`, `service_retabli`, `interruption_planifiee_a_venir`, `interruption_planifiee_reportee`, `interruption_planifiee_annulee`.

**`retablissement`** : `en_evaluation`, `prevu`, `en_revision`.

**`niveau_urgence`** : `normal`, `panne_majeure`.

**`cause`** : une des 23 causes d'Info-pannes, par exemple `foudre`, `vents_violents`, `dommages_vegetation` ou `indeterminee`. La liste complète est dans l'attribut `options` de l'entité.

## Exemples d'automatisation

### Notification lors d'une panne

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.maison_etat_du_service
    to: "on"
actions:
  - action: notify.mobile_app
    data:
      title: "⚡ Panne électrique"
      message: >
        Cause : {{ state_translated('sensor.maison_cause') }}.
        Rétablissement estimé : {{ states('sensor.maison_date_fin') }}.
```

### Rappel la veille d'une interruption planifiée

```yaml
triggers:
  - trigger: calendar
    event: start
    offset: "-12:00:00"
    entity_id: calendar.maison_interruptions_planifiees
actions:
  - action: notify.mobile_app
    data:
      title: "📅 Interruption planifiée demain"
      message: >
        De {{ as_timestamp(trigger.calendar_event.start) | timestamp_custom('%H:%M') }}
        à {{ as_timestamp(trigger.calendar_event.end) | timestamp_custom('%H:%M') }}.
```

## Événement `hydropannes_data_changed`

Émis à chaque changement des données d'un lieu, avec `entry_id`, `lieu_consommation`, `timestamp` et le payload complet dans `data`. Utile pour journaliser les changements. Le premier relevé après un démarrage n'émet rien.

## Dépannage

- **Le numéro est refusé** : il doit comporter exactement 10 chiffres.
- **Les entités sont indisponibles** : l'API d'Hydro-Québec ne répond pas ou a répondu dans un format inattendu. Le message d'erreur est dans les journaux, et une carte apparaît dans **Réparations** si la structure de l'API a changé.
- **Signaler un problème** : joignez le rapport de diagnostic (les 3 points du lieu → **Télécharger les diagnostics**, le numéro de lieu y est masqué) à une [issue](https://github.com/johnjohn-11/hydropannes/issues).

## Crédits

Données fournies par [Hydro-Québec](https://www.hydroquebec.com/) via l'API publique d'Info-pannes. Merci à [@nxor](https://github.com/nxor) et [@MivraMe](https://github.com/MivraMe), dont la solution à base de template sensors a inspiré cette intégration.

Licence MIT, voir [LICENSE](LICENSE). Les contributions sont les bienvenues par issue ou pull request.
