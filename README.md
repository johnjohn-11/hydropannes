# Hydro-Pannes

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/johnjohn-11/hydropannes.svg)](https://github.com/johnjohn-11/hydropannes/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-blue.svg)](https://www.home-assistant.io/)

Intégration Home Assistant pour surveiller les pannes d'électricité d'Hydro-Québec.

Suivez en temps réel l'état du service électrique pour un ou plusieurs lieux de consommation : pannes en cours, interventions planifiées et estimation du rétablissement.

> ⚠️ **Cette intégration n'est pas affiliée à Hydro-Québec.**
> En cas de problème, ouvrez une [issue sur GitHub](https://github.com/johnjohn-11/hydropannes/issues).
> **Ne contactez pas le service à la clientèle d'Hydro-Québec.**

> 🔴 **Changement incompatible en 2.0.0 — les états des sensors ont changé.**
> Les sensors `info_pannes`, `niveau_urgence`, `cause` et `statut_intervention`
> exposent désormais un **identifiant neutre en langue** (ex. `panne_en_cours`)
> au lieu du libellé français (ex. `Panne en cours`), conformément aux
> conventions Home Assistant pour les sensors de type énumération.
> Le libellé traduit reste affiché dans l'interface.
> **Toute automatisation qui compare l'état à un texte français doit être mise à jour** :
> voir [Migration vers la 2.0.0](#migration-vers-la-200).

---

## Fonctionnalités

- 🔌 **État du service** : Détection des pannes en temps réel
- 📅 **Interventions planifiées** : Travaux annoncés à l'avance
- ⏱️ **Durée de la panne** : Temps écoulé depuis le début
- 🕐 **Estimation de rétablissement** : Compte à rebours avant le retour du courant
- 👥 **Adresses touchées** : Nombre de clients affectés
- 🔧 **Statut d'intervention** : Évaluation, équipe en route, travaux en cours, etc.
- 📍 **Multi-lieux** : Surveillance de plusieurs adresses indépendantes
- ⚡ **Polling adaptatif** : Mise à jour toutes les 60 s pendant une panne, 3 min sinon
- 📊 **Données post-panne** : Informations conservées après le rétablissement
- 🔍 **Historique API** : Les 5 derniers changements de données conservés pour le diagnostic
- 🔔 **Événement de changement** : `hydropannes_data_changed` émis à chaque changement des données de l'API

---

## Installation

### HACS (recommandé)

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=johnjohn-11&repository=hydropannes&category=integration)

Ou manuellement :

1. Ouvrir HACS dans Home Assistant
2. Cliquer sur les 3 points en haut à droite → **Dépôts personnalisés**
3. Ajouter l'URL `https://github.com/johnjohn-11/hydropannes` avec la catégorie **Intégration**
4. Rechercher « Hydro-Pannes » et installer
5. Redémarrer Home Assistant

### Installation manuelle

1. Télécharger la dernière [release](https://github.com/johnjohn-11/hydropannes/releases/latest)
2. Copier le dossier `custom_components/hydropannes` dans votre dossier `config/custom_components/`
3. Redémarrer Home Assistant

---

## Configuration

### Ajouter un lieu de consommation

[![Ajouter l'intégration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hydropannes)

Ou manuellement :

1. **Paramètres** → **Appareils et services** → **+ Ajouter une intégration**
2. Rechercher « Hydro-Pannes »
3. Entrer votre **numéro de lieu de consommation** (10 chiffres — voir le guide ci-dessous pour le trouver)
4. Donner un **nom** à ce lieu (ex. : « Maison », « Chalet »)

Répétez l'opération pour chaque lieu à surveiller. Chaque lieu crée un appareil indépendant avec ses propres entités.

> 📖 **Trouver votre numéro de lieu de consommation** : [Guide domo-quebec](https://github.com/domo-quebec/domo-quebec/blob/main/hydro-quebec/configuration_info-panne.md)

### Modifier le nom d'un lieu

1. **Paramètres** → **Appareils et services** → **Hydro-Pannes**
2. Cliquer sur **Configurer** (icône engrenage) à côté du lieu
3. Modifier le nom et sauvegarder

### Modifier le numéro de lieu de consommation

Si vous avez saisi un mauvais numéro, corrigez-le sans supprimer l'appareil
(les entités et l'historique sont conservés) :

1. **Paramètres** → **Appareils et services** → **Hydro-Pannes**
2. Cliquer sur les 3 points à côté du lieu → **Reconfigurer**
3. Entrer le nouveau numéro et sauvegarder

---

## Entités créées

Chaque lieu de consommation configuré crée un appareil avec les entités suivantes.

### Sensors

| Entité | Description |
|--------|-------------|
| `sensor.*_info_pannes` | État général du service (voir [tableau des états](#états-du-sensor-info-pannes)) |
| `sensor.*_niveau_urgence` | Niveau d'urgence : Normal ou Panne majeure |
| `sensor.*_adresses_touchees` | Nombre de clients affectés |
| `sensor.*_date_debut` | Date et heure de début de la panne ou de l'intervention |
| `sensor.*_date_fin` | Date et heure de fin réelle ou estimée |
| `sensor.*_statut_intervention` | Étape de l'intervention (équipe désignée, travaux en cours, etc.) |
| `sensor.*_cause` | Cause de la panne (le code brut d'Hydro-Québec reste dans l'attribut `code_cause`) |
| `sensor.*_duree` | Durée de la panne en secondes |
| `sensor.*_delai_avant_retablissement` | Temps restant avant le rétablissement estimé |
| `sensor.*_derniere_maj` | Horodatage de la dernière mise à jour des données |
| `sensor.*_lieu_de_consommation` | Numéro de lieu de consommation *(Diagnostic)* |

### Binary Sensors

| Entité | Description |
|--------|-------------|
| `binary_sensor.*_etat_du_service` | `on` = panne active ou intervention planifiée en cours, `off` = service normal |
| `binary_sensor.*_intervention_planifiee` | `on` = intervention planifiée active ou à venir |
| `binary_sensor.*_compatibilite_api` | `on` = structure de l'API Hydro-Québec modifiée *(Diagnostic)* |

> 💡 Les entités de catégorie **Diagnostic** sont masquées par défaut dans l'interface. Elles sont accessibles via **Paramètres** → **Appareils et services** → appareil → **Entités de diagnostic**.

---

## États des sensors

Les quatre sensors ci-dessous sont des énumérations (`device_class: enum`).
Leur **état** est un identifiant stable et neutre en langue, celui que renvoie
`states()` et qu'il faut utiliser dans les automatisations. Le **libellé**
affiché dans l'interface est traduit ; on le récupère dans un template avec
`state_translated('sensor.xxx')`.

### `sensor.*_info_pannes`

| État | Libellé affiché (fr) | Description |
|------|----------------------|-------------|
| `aucune_panne` | Aucune panne détectée | Service normal, aucune interruption |
| `panne_en_cours` | Panne en cours | Panne non planifiée active |
| `panne_majeure` | Panne majeure en cours | Panne de grande envergure |
| `reprise_graduelle` | Rétablissement graduel du service en cours | Retour progressif du courant |
| `service_retabli` | Service rétabli | Panne terminée récemment |
| `aip_en_cours` | Interruption planifiée en cours | Travaux planifiés en cours d'exécution |
| `aip_a_venir` | Interruption planifiée à venir | Travaux planifiés annoncés pour plus tard |
| `aip_terminee` | Interruption planifiée terminée | Travaux planifiés complétés |
| `aip_annulee` | Interruption planifiée annulée | Travaux planifiés annulés par Hydro-Québec |
| `aip_reportee` | Interruption planifiée reportée | Travaux planifiés reportés à une nouvelle date |

### `sensor.*_niveau_urgence`

| État | Libellé affiché (fr) |
|------|----------------------|
| `normal` | Normal |
| `panne_majeure` | Panne majeure |

### `sensor.*_cause`

| État | Libellé affiché (fr) |
|------|----------------------|
| `accident_ou_incident` | Accident ou incident |
| `amelioration_entretien_reseau` | Amélioration ou entretien du réseau |
| `bris_equipement` | Bris d'équipement |
| `conditions_meteorologiques` | Conditions météorologiques |
| `dommages_animal` | Dommages dus à un animal |
| `dommages_vegetation` | Dommages dus à la végétation |
| `incendie_ou_fuite_gaz` | Incendie ou fuite de gaz |
| `securite_publique` | Interruption - Sécurité publique |
| `travaux_renforcement_reseau` | Travaux planifiés - Renforcement de réseau |
| `travaux_vegetation_elagage` | Travaux sur la végétation ou élagage |
| `usure_materiel` | Usure ou désagrégation de matériel |
| `indeterminee` | Indéterminée *(Hydro-Québec ne fournit aucun code)* |
| `inconnue` | Inconnue *(code non encore reconnu par l'intégration)* |

Plusieurs codes d'Hydro-Québec partagent un même état ; le code brut reste
disponible dans l'attribut `code_cause`.

### `sensor.*_statut_intervention`

| État | Libellé affiché (fr) |
|------|----------------------|
| `evaluation_travaux` | Évaluation des travaux requis |
| `equipe_designee` | Équipe désignée |
| `equipe_en_route` | Équipe en route |
| `travaux_en_cours` | Travaux en cours sur le réseau électrique |
| `travaux_par_priorite` | Réalisation des travaux par ordre de priorité |
| `retablissement_en_evaluation` | Heure de rétablissement en cours d'évaluation |
| `retablissement_prevu` | Rétablissement prévu |
| `fin_non_determinee` | Fin non déterminée |
| `reprise_graduelle` | Rétablissement graduel du service en cours |
| `service_retabli` | Service rétabli |
| `aip_a_venir` | Interruption planifiée à venir |
| `aip_reportee` | Interruption planifiée reportée |

---

## Migration vers la 2.0.0

Avant la 2.0.0, ces sensors renvoyaient directement le libellé français. Une
automatisation écrite ainsi ne se déclenche plus :

```yaml
# ❌ Ne fonctionne plus
condition:
  - condition: state
    entity_id: sensor.hydropannes_maison_info_pannes
    state: "Panne en cours"
```

Remplacez le libellé par l'identifiant correspondant :

```yaml
# ✅ Correct
condition:
  - condition: state
    entity_id: sensor.hydropannes_maison_info_pannes
    state: "panne_en_cours"
```

Pour afficher le libellé traduit dans une notification, utilisez
`state_translated` :

```yaml
message: "Cause : {{ state_translated('sensor.hydropannes_maison_cause') }}"
```

Les sensors non énumérés (dates, durées, nombre de clients) et les binary
sensors sont inchangés.

---

## Logique de priorité

Lorsqu'une panne et une intervention planifiée coexistent, l'intégration sélectionne l'interruption à afficher selon cet ordre de priorité :

1. **Panne active** (non planifiée, courant coupé): priorité absolue
2. **Panne terminée** (courant rétabli), sauf si une interruption planifiée non annulée est également présente
3. **Intervention planifiée** (active, à venir, ou terminée)
4. **Première interruption de la liste**: dernier recours

---

## Fréquence de mise à jour

| Situation | Intervalle |
|-----------|------------|
| Panne active | **60 secondes** |
| Aucune panne | **3 minutes** |

En cas d'erreur réseau ou d'API indisponible, les sensors conservent leur dernière valeur connue et une nouvelle tentative est effectuée lors du prochain cycle.

---

## Exemples d'automatisation

### Notification lors d'une panne

```yaml
automation:
  - alias: "Notification panne électrique"
    trigger:
      - platform: state
        entity_id: binary_sensor.hydropannes_maison_etat_du_service
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "⚡ Panne électrique"
          message: >
            Panne détectée à {{ now().strftime('%H:%M') }}.
            Cause : {{ state_translated('sensor.hydropannes_maison_cause') }}.
            Rétablissement estimé : {{ states('sensor.hydropannes_maison_date_fin') }}.
```

### Notification au rétablissement

```yaml
automation:
  - alias: "Notification courant rétabli"
    trigger:
      - platform: state
        entity_id: binary_sensor.hydropannes_maison_etat_du_service
        from: "on"
        to: "off"
    action:
      - service: notify.mobile_app
        data:
          title: "✅ Courant rétabli"
          message: >
            Le courant est rétabli après
            {{ (states('sensor.hydropannes_maison_duree') | int / 3600) | round(1) }} h.
```

## Journaliser les changements (événement)

À chaque changement de données d'un lieu, l'intégration émet l'événement
`hydropannes_data_changed` sur le bus Home Assistant, avec le payload complet :

| Champ | Description |
|-------|-------------|
| `entry_id` | Identifiant de l'entrée de configuration |
| `lieu_consommation` | Numéro de lieu de consommation |
| `timestamp` | Horodatage UTC du changement |
| `data` | Payload brut complet renvoyé par l'API |


## Diagnostics

Pour obtenir les données de diagnostic (utile pour signaler un problème) :

1. **Paramètres** → **Appareils et services** → **Hydro-Pannes**
2. Cliquer sur les 3 points → **Télécharger les diagnostics**

Le rapport inclut :
- L'état actuel des données API (numéro de lieu masqué automatiquement)
- L'historique des 5 derniers changements de payload détectés
- L'intervalle de polling actuel
- L'horodatage de la dernière mise à jour réussie
- L'état de compatibilité de l'API

---

## Dépannage

**L'intégration refuse mon numéro de lieu**
Vérifiez que le numéro comporte exactement 10 chiffres.

**Les sensors affichent « Indisponible »**
Le coordinator n'a pas encore reçu de données valides. Vérifiez votre connexion internet et consultez les logs Home Assistant (**Paramètres** → **Système** → **Journaux**).

**Les sensors restent sur leur ancienne valeur**
Comportement normal en cas d'erreur réseau transitoire. Les données sont conservées jusqu'au prochain cycle réussi.

**Le sensor `compatibilite_api` est `on` (ou une alerte apparaît dans Réparations)**
L'API Hydro-Québec a probablement modifié sa structure. Une carte est aussi
ajoutée dans **Paramètres** → **Appareils et services** → **Réparations**.
Vérifiez si une mise à jour de l'intégration est disponible dans HACS et ouvrez une [issue](https://github.com/johnjohn-11/hydropannes/issues) si le problème persiste.

---

## Attribution

Les données sont fournies par [Hydro-Québec](https://www.hydroquebec.com/) via leur API publique Info-pannes.

## Remerciements

Merci à [@nxor](https://github.com/nxor) et [@MivraMe](https://github.com/MivraMe) pour leur travail sur une solution basée sur des templates sensor, qui a inspiré cette intégration.

## Licence

Ce projet est sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Contribution

Les contributions sont les bienvenues ! Ouvrez une issue ou une pull request sur GitHub.
