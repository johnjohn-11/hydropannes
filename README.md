# Hydro-Pannes

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jfparis84/hydro-pannes.svg)](https://github.com/jfparis84/hydro-pannes/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Intégration Home Assistant pour surveiller les pannes d'électricité d'Hydro-Québec.

Cette intégration permet de suivre en temps réel l'état du service électrique pour un ou plusieurs lieux de consommation, incluant les pannes en cours et les interventions planifiées.

## Fonctionnalités

- 🔌 **État du service** - Détection des pannes en temps réel
- 📅 **Interventions planifiées** - Notification des travaux à venir
- ⏱️ **Durée de la panne** - Temps écoulé depuis le début
- 🕐 **Estimation de rétablissement** - Temps restant avant le retour du courant
- 👥 **Adresses touchées** - Nombre de clients affectés
- 🔧 **Statut d'intervention** - Équipe en route, au travail, etc.
- 📍 **Multi-lieux** - Surveillance de plusieurs adresses

## Installation

### HACS (recommandé)

1. Ouvrir HACS dans Home Assistant
2. Cliquer sur les 3 points en haut à droite → **Dépôts personnalisés**
3. Ajouter l'URL du dépôt : `https://github.com/jfparis84/hydro-pannes`
4. Catégorie : **Intégration**
5. Cliquer sur **Ajouter**
6. Rechercher "Hydro-Pannes" et installer
7. Redémarrer Home Assistant

### Installation manuelle

1. Télécharger le contenu de ce dépôt
2. Copier le dossier `custom_components/hydro_pannes` dans votre dossier `config/custom_components/`
3. Redémarrer Home Assistant

## Configuration

1. Aller dans **Paramètres** → **Appareils et services**
2. Cliquer sur **+ Ajouter une intégration**
3. Rechercher "Hydro-Pannes"
4. Entrer votre **numéro de lieu de consommation** (visible sur votre facture Hydro-Québec)
5. Donner un **nom** à ce lieu (ex: "Maison", "Chalet")

### Trouver votre numéro de lieu de consommation

Le numéro de lieu de consommation se trouve sur votre facture Hydro-Québec. C'est un numéro à 10 chiffres qui identifie votre adresse de service.

## Entités créées

### Sensors

| Entité | Description |
|--------|-------------|
| `sensor.hydropannes_*_info_pannes` | État général (Panne en cours, Courant rétabli, etc.) |
| `sensor.hydropannes_*_niveau_urgence` | Niveau d'urgence (Panne, Panne majeure) |
| `sensor.hydropannes_*_adresses_touchees` | Nombre de clients affectés |
| `sensor.hydropannes_*_debut` | Date/heure de début de la panne |
| `sensor.hydropannes_*_date_fin_estimee_ou_reelle` | Date/heure de fin (réelle ou estimée) |
| `sensor.hydropannes_*_statut_intervention` | Statut de l'équipe d'intervention |
| `sensor.hydropannes_*_cause` | Cause de la panne |
| `sensor.hydropannes_*_duree` | Durée de la panne |
| `sensor.hydropannes_*_duree_avant_retablissement` | Temps restant estimé |
| `sensor.hydropannes_*_derniere_maj` | Dernière mise à jour des données |
| `sensor.hydropannes_*_lieu_conso` | Numéro de lieu de consommation (diagnostic) |

### Binary Sensors

| Entité | Description |
|--------|-------------|
| `binary_sensor.hydropannes_*_etat_service` | ON = Panne en cours, OFF = Service normal |
| `binary_sensor.hydropannes_*_intervention_planifiee` | ON = Intervention planifiée existe |

## États du sensor Info-pannes

| État | Description |
|------|-------------|
| `Aucune panne détectée` | Service normal |
| `Panne en cours` | Panne non planifiée active |
| `Courant rétabli` | Panne terminée récemment |
| `Intervention planifiée en cours` | Travaux planifiés en cours |
| `Intervention planifiée terminée` | Travaux planifiés terminés |
| `Interruption planifiée à venir` | Travaux planifiés annoncés |

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
            Cause: {{ states('sensor.hydropannes_maison_cause') }}
            Rétablissement estimé: {{ states('sensor.hydropannes_maison_date_fin_estimee_ou_reelle') }}

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
            Le courant est rétabli après {{ states('sensor.hydropannes_maison_duree') }}.
```

## Logique de priorité

L'intégration gère les situations où une panne et une intervention planifiée existent simultanément :

1. **Priorité 1** : Panne en cours (non planifiée)
2. **Priorité 2** : Intervention planifiée

Les sensors affichent toujours les informations de la panne réelle en priorité sur une intervention planifiée.

## Fréquence de mise à jour

Les données sont récupérées de l'API Hydro-Québec toutes les **60 secondes** par défaut.

Si l'API est inaccessible ou ne retourne pas de données, les sensors conservent leur dernière valeur connue.

## Dépannage

### L'intégration ne trouve pas mon lieu de consommation

- Vérifiez que le numéro de lieu de consommation est correct (10 chiffres)
- Vérifiez que votre compte Hydro-Québec est actif

### Les sensors affichent "Inconnu"

- Cela signifie qu'il n'y a aucune panne ou intervention en cours
- C'est le comportement normal quand tout va bien

### Les données ne se mettent pas à jour

- Vérifiez votre connexion internet
- Consultez les logs Home Assistant pour les erreurs

## Attribution

Les données sont fournies par [Hydro-Québec](https://www.hydroquebec.com/) via leur API publique Info-pannes.

## Licence

Ce projet est sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.
