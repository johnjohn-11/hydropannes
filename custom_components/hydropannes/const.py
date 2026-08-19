"""Constants for the Hydro-Pannes integration."""

DOMAIN = "hydropannes"

CONF_LIEU_CONSO = "lieu_consommation"
CONF_NOM_LIEU = "nom_lieu"

# Option (entry.options): enable the on-disk JSONL change log (opt-in).
CONF_JSON_LOG = "json_log"

API_URL = "https://services-bs.solutions.hydroquebec.com/pan/web/api/v1/lieux-conso/etats/{}"

UPDATE_INTERVAL = 180  # seconds — default polling interval (no active outage)

ATTRIBUTION = "Données fournies par Hydro-Québec"

CAUSE_CODES = {
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
    "33": "Usure ou désagrégation de matériel",
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
    "63": "Amélioration ou entretien du réseau",
    "68": "Travaux planifiés - Renforcement de réseau",
    "71": "Amélioration ou entretien du réseau",
    "77": "Travaux sur la végétation ou élagage",
}

INTERVENTION_CODES = {
    "N": "Évaluation des travaux requis",
    "A": "Équipe désignée",
    "R": "Équipe en route",
    "L": "Travaux en cours sur le réseau électrique",
}

# Overrides INTERVENTION_CODES["L"] for major outages (niveauUrgence = "P").
INTERVENTION_CODES_MAJEUR = {
    "L": "Réalisation des travaux par ordre de priorité",
}

NIVEAU_URGENCE_CODES = {
    "N": "Normal",
    "P": "Panne majeure",
}

# typeFinPrevue → ETAPE-PANNE step 5 label.
# U, D, P: documented by HQ.
# F, E, X: observed empirically; labels are provisional.
TYPE_FIN_PREVUE_CODES = {
    "U": "Heure de rétablissement en cours d'évaluation",  # no estimated date
    "D": "Rétablissement prévu",  # reliable date
    "P": "Rétablissement prévu",  # major outage, delays not guaranteed
    "F": "Fin non déterminée",  # major outage, no dateFinEstimeeMax
    "E": "Rétablissement prévu",  # major outage, dateFinEstimeeMax present (estimated)
    "X": "Rétablissement prévu",  # observed near end of major outage; exact meaning unconfirmed
}

# Codes that indicate a rescheduled AIP (original slot cancelled, new date assigned).
# codeRemarque meanings (observed empirically): "91" changement à la demande d'un
# tiers, "92" annulation d'une AIP, "93" report d'une AIP ("91" confirmed in prod).
AIP_REPORT_CODES = {"91", "93"}

ETAT_INTERRUPTION_CODES = {
    "C": "En cours d'évaluation",
    "N": "Non-alimenté",
    "T": "Terminée",
    "P": "Planifiée",
    "R": "Reportée",
    "A": "Annulée",
}

# Canonical state strings matching HQ TYPE-DE-PANNES labels.
INFO_PANNES_STATES = {
    "aucune_panne": "Aucune panne détectée",
    "panne_en_cours": "Panne en cours",
    "panne_majeure": "Panne majeure en cours",
    "reprise_graduelle": "Rétablissement graduel du service en cours",
    "service_retabli": "Service rétabli",
    "aip_en_cours": "Interruption planifiée en cours",
    "aip_a_venir": "Interruption planifiée à venir",
    "aip_terminee": "Interruption planifiée terminée",
    "aip_annulee": "Interruption planifiée annulée",
    "aip_reportee": "Interruption planifiée reportée",
}
