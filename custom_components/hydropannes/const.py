"""Constants for the Hydro-Pannes integration."""

from typing import Final

DOMAIN: Final[str] = "hydropannes"

CONF_LIEU_CONSO: Final[str] = "lieu_consommation"
CONF_NOM_LIEU: Final[str] = "nom_lieu"

API_URL: Final[str] = (
    "https://services-bs.solutions.hydroquebec.com/"
    "pan/web/api/v1/lieux-conso/etats/{}"
)

UPDATE_INTERVAL: Final[int] = 180  # seconds

ATTRIBUTION: Final[str] = "Données fournies par Hydro-Québec"

CAUSE_CODES: Final[dict[str, str]] = {
    "11": "Bris d'équipement",
    "12": "Bris d'équipement",
    "13": "Bris d'équipement",
    "14": "Bris d'équipement",
    "15": "Bris d'équipement",
    "58": "Bris d'équipement",
    "70": "Bris d'équipement",
    "72": "Bris d'équipement",
    "73": "Bris d'équipement",
    "74": "Bris d'équipement",
    "79": "Bris d'équipement",
    "21": "Conditions météorologiques",
    "22": "Conditions météorologiques",
    "24": "Conditions météorologiques",
    "25": "Conditions météorologiques",
    "26": "Conditions météorologiques",
    "31": "Accident ou incident",
    "32": "Accident ou incident",
    "33": "Accident ou incident",
    "34": "Incendie ou fuite de gaz",
    "41": "Accident ou incident",
    "42": "Accident ou incident",
    "43": "Accident ou incident",
    "44": "Interruption - Sécurité publique",
    "54": "Accident ou incident",
    "55": "Accident ou incident",
    "56": "Accident ou incident",
    "57": "Accident ou incident",
    "51": "Dommages dus à la végétation",
    "52": "Dommages dus à un animal",
    "53": "Dommages dus à un animal",
    "68": "Travaux planifiés - Remforcement de réseau",
    "71": "Amélioration ou entretien du réseau",
}

INTERVENTION_CODES: Final[dict[str, str]] = {
    "A": "Travaux assignés",
    "L": "Équipe au travail",
    "R": "Équipe en route",
}
