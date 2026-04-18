# Hydro-Pannes

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/johnjohn-11/hydropannes.svg)](https://github.com/johnjohn-11/hydropannes/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

Intégration Home Assistant pour surveiller les pannes d'électricité d'Hydro-Québec.

Suivez en temps réel l'état du service électrique pour un ou plusieurs lieux de consommation: pannes en cours, interventions planifiées et estimation du rétablissement.

> ⚠️ **Cette intégration n'est pas affiliée à Hydro-Québec.**
> En cas de problème, ouvrez une [issue sur GitHub](https://github.com/johnjohn-11/hydropannes/issues).
> **Ne contactez pas le service à la clientèle d'Hydro-Québec.**

## Fonctionnalités

- 🔌 **État du service** — Détection des pannes en temps réel
- 📅 **Interventions planifiées** — Travaux annoncés à l'avance
- ⏱️ **Durée de la panne** — Temps écoulé depuis le début
- 🕐 **Estimation de rétablissement** — Compte à rebours avant le retour du courant
- 👥 **Adresses touchées** — Nombre de clients affectés
- 🔧 **Statut d'intervention** — Évaluation, équipe en route, travaux en cours, etc.
- 📍 **Multi-lieux** — Surveillance de plusieurs adresses indépendantes
- ⚡ **Polling adaptatif** — Mise à jour toutes les 60 s pendant une panne, 3 min sinon
- 📊 **Données post-panne** — Informations conservées après le rétablissement

## Installation

### HACS (recommandé)

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=johnjohn-11&repository=hydropannes&category=integration)

Ou manuellement :

1. Ouvrir HACS dans Home Assistant
2. Cliquer sur les 3 points en haut à droite → **Dépôts personnalisés**
3. Ajouter l'URL : `https://github.com/johnjohn-11/hydropannes` — Catégorie : **Intégration**
4. Rechercher « Hydro-Pannes » et installer
5. Redémarrer Home Assistant

### Installation manuelle

1. Télécharger le contenu de ce dépôt
2. Copier le dossier `custom_components/hydropannes` dans `config/custom_components/`
3. Redémarrer Home Assistant

## Configuration

### Ajouter un lieu

[![Ajouter l'intégration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hydropannes)

Ou manuellement :

1. **Paramètres** → **Appareils et services** → **+ Ajouter une intégration**
2. Rechercher « Hydro-Pannes »
3. Entrer votre **numéro de lieu de consommation** (visible sur votre facture Hydro-Québec)
4. Donner un **nom** à ce lieu (ex : « Maison », « Chalet »)

Répétez l'opération pour chaque lieu à surveiller. Chaque lieu crée un appareil indépendant.

### Modifier le nom du lieu

1. **Paramètres** → **Appareils et services** → **Hydro-Pannes**
2. Cliquer sur **Configurer** (icône engrenage)
3. Modifier le nom et sauvegarder

### Trouver votre numéro de lieu de consommation

Consultez le guide : [Comment trouver votre lieu de consommation](https://github.com/domo-quebec/domo-quebec/blob/main/hydro-quebec/configuration_info-panne.md)

## Entités créées

### Sensors

| Entité | Description |
|--------|-------------|
| `sensor.*_info_pannes` | État général du service (voir tableau des états ci-dessous) |
| `sensor.*_niveau_urgence` | Niveau d'urgence : Normal ou Panne majeure |
| `sensor.*_adresses_touchees` | Nombre de clients affectés |
| `sensor.*_date_debut` | Date/heure de début de la panne ou de l'intervention |
| `sensor.*_date_fin` | Date/heure de fin réelle ou estimée |
| `sensor.*_statut_intervention` | Étape de l'intervention (équipe désignée, travaux en cours, etc.) |
| `sensor.*_cause` | Cause de la panne |
| `sensor.*_duree` | Durée de la panne en secondes |
| `sensor.*_duree_avant_retablissement` | Temps restant avant le rétablissement estimé |
| `sensor.*_derniere_maj` | Horodatage de la dernière mise à jour des données |
| `sensor.*_lieu_conso` | Numéro de lieu de consommation — catégorie Diagnostic |

### Binary Sensors

| Entité | Description |
|--------|-------------|
| `binary_sensor.*_etat_service` | `on` = panne active, `off` = service normal |
| `binary_sensor.*_intervention_planifiee` | `on` = intervention planifiée en cours ou à venir |

## États du sensor Info-pannes

| État | Description |
|------|-------------|
| `Aucune panne détectée` | Service normal, aucune interruption |
| `Panne en cours` | Panne non planifiée active |
| `Panne majeure en cours` | Panne de grande envergure (niveauUrgence = P) |
| `Rétablissement graduel du service en cours` | Retour progressif du courant (GRAP) |
| `Service rétabli` | Panne terminée récemment |
| `Interruption planifiée en cours` | Travaux planifiés en cours d'exécution |
| `Interruption planifiée à venir` | Travaux planifiés annoncés pour plus tard |
| `Interruption planifiée terminée` | Travaux planifiés complétés |
| `Interruption planifiée annulée` | Travaux planifiés annulés par Hydro-Québec |

## Logique de priorité

Lorsqu'une panne et une intervention planifiée coexistent, l'intégration applique la logique suivante pour déterminer quelle interruption afficher :

1. **Panne active** (non planifiée, courant coupé) — priorité absolue
2. **Panne terminée** (courant rétabli) — sauf si une interruption planifiée non annulée est également présente
3. **Intervention planifiée** (active, à venir, ou terminée)
4. **Première interruption de la liste** — dernier recours

## Fréquence de mise à jour

| Situation | Intervalle |
|-----------|------------|
| Panne active | **60 secondes** |
| Aucune panne | **3 minutes** |

En cas d'erreur réseau ou d'API indisponible, les sensors conservent leur dernière valeur connue et une nouvelle tentative est effectuée lors du prochain cycle.

## Exemple d'automatisation

```yaml
automation:
  - alias: "Notification panne électrique"
    trigger:
      - platform: state
        entity_id: binary_sensor.hydropannes_maison_etat_service
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "⚡ Panne électrique"
          message: >
            Panne détectée à {{ now().strftime('%H:%M') }}.
            Cause : {{ states('sensor.hydropannes_maison_cause') }}.
            Rétablissement estimé : {{ states('sensor.hydropannes_maison_date_fin') }}.

  - alias: "Notification courant rétabli"
    trigger:
      - platform: state
        entity_id: binary_sensor.hydropannes_maison_etat_service
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

## Diagnostics

Pour obtenir les données de diagnostic (utile pour signaler un problème) :

1. **Paramètres** → **Appareils et services** → **Hydro-Pannes**
2. Cliquer sur les 3 points → **Télécharger les diagnostics**

Le numéro de lieu de consommation est automatiquement masqué dans le rapport.

## Dépannage

**L'intégration refuse mon numéro de lieu**
Vérifiez que le numéro est correct (format numérique, visible sur votre facture). L'API Hydro-Québec doit retourner des données pour ce lieu.

**Les sensors affichent « Indisponible »**
Le coordinator n'a pas encore reçu de données valides. Vérifiez votre connexion internet et consultez les logs Home Assistant.

**Les sensors restent sur leur ancienne valeur**
Comportement normal en cas d'erreur réseau transitoire — les données sont conservées jusqu'au prochain cycle réussi.

## Attribution

Les données sont fournies par [Hydro-Québec](https://www.hydroquebec.com/) via leur API publique Info-pannes.

## Remerciements

Merci à [@nxor](https://github.com/nxor) et [@MivraMe](https://github.com/MivraMe) pour leur travail sur une solution basée sur des templates sensor, qui a inspiré cette intégration.

## Licence

Ce projet est sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Contribution

Les contributions sont les bienvenues ! Ouvrez une issue ou une pull request sur GitHub.
