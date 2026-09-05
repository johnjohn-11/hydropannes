"""Constants for the Hydro-Pannes integration.

Enumerated sensors expose language-neutral slugs as their state, following the
Home Assistant ``SensorDeviceClass.ENUM`` convention. The code-to-slug maps
live here; the human-readable labels live in ``strings.json`` under
``entity.sensor.<translation_key>.state`` and are translated per language.
"""

DOMAIN = "hydropannes"

CONF_LIEU_CONSO = "lieu_consommation"
CONF_NOM_LIEU = "nom_lieu"

# Bus event fired whenever a location's API payload changes. Carries the full
# payload so users can log or react to changes from their own automations.
EVENT_DATA_CHANGED = f"{DOMAIN}_data_changed"

API_URL = "https://services-bs.solutions.hydroquebec.com/pan/web/api/v1/lieux-conso/etats/{}"

UPDATE_INTERVAL = 180  # seconds — default polling interval (no active outage)

ATTRIBUTION = "Données fournies par Hydro-Québec"

# ---------------------------------------------------------------------------
# sensor.*_info_pannes
# ---------------------------------------------------------------------------

# Every state the info-pannes sensor can report. A value outside this list is
# rejected by Home Assistant, so the sensor returns None rather than inventing
# a state for data it does not recognize.
INFO_PANNES_OPTIONS = [
    "aucune_panne",
    "panne_en_cours",
    "panne_majeure",
    "reprise_graduelle",
    "service_retabli",
    "aip_en_cours",
    "aip_a_venir",
    "aip_terminee",
    "aip_annulee",
    "aip_reportee",
]

# ---------------------------------------------------------------------------
# sensor.*_niveau_urgence
# ---------------------------------------------------------------------------

NIVEAU_URGENCE_CODES = {
    "N": "normal",
    "P": "panne_majeure",
}

NIVEAU_URGENCE_OPTIONS = ["normal", "panne_majeure"]

# ---------------------------------------------------------------------------
# sensor.*_cause
# ---------------------------------------------------------------------------

# codeCause → slug. The raw code is exposed as the ``code_cause`` attribute so
# no information is lost by mapping several codes onto one slug.
CAUSE_CODES = {
    "11": "bris_equipement",
    "12": "bris_equipement",
    "13": "bris_equipement",
    "14": "bris_equipement",
    "15": "bris_equipement",
    "58": "bris_equipement",
    "70": "bris_equipement",
    "72": "bris_equipement",
    "73": "bris_equipement",
    "74": "bris_equipement",
    "79": "bris_equipement",
    "21": "conditions_meteorologiques",
    "22": "conditions_meteorologiques",
    "24": "conditions_meteorologiques",
    "25": "conditions_meteorologiques",
    "26": "conditions_meteorologiques",
    "31": "accident_ou_incident",
    "32": "accident_ou_incident",
    "33": "usure_materiel",
    "34": "incendie_ou_fuite_gaz",
    "41": "accident_ou_incident",
    "42": "accident_ou_incident",
    "43": "accident_ou_incident",
    "44": "securite_publique",
    "54": "accident_ou_incident",
    "55": "accident_ou_incident",
    "56": "accident_ou_incident",
    "57": "accident_ou_incident",
    "51": "dommages_vegetation",
    "52": "dommages_animal",
    "53": "dommages_animal",
    "63": "amelioration_entretien_reseau",
    "68": "travaux_renforcement_reseau",
    "71": "amelioration_entretien_reseau",
    "77": "travaux_vegetation_elagage",
}

CAUSE_OPTIONS = [
    "accident_ou_incident",
    "amelioration_entretien_reseau",
    "bris_equipement",
    "conditions_meteorologiques",
    "dommages_animal",
    "dommages_vegetation",
    "incendie_ou_fuite_gaz",
    "indeterminee",
    "inconnue",
    "securite_publique",
    "travaux_renforcement_reseau",
    "travaux_vegetation_elagage",
    "usure_materiel",
]

# ---------------------------------------------------------------------------
# sensor.*_statut_intervention
# ---------------------------------------------------------------------------

INTERVENTION_CODES = {
    "N": "evaluation_travaux",
    "A": "equipe_designee",
    "R": "equipe_en_route",
    "L": "travaux_en_cours",
}

# Overrides INTERVENTION_CODES["L"] for major outages (niveauUrgence = "P").
INTERVENTION_CODES_MAJEUR = {
    "L": "travaux_par_priorite",
}

# typeFinPrevue → slug.
# U, D, P: documented by HQ.
# F, E, X: observed empirically; meanings are provisional.
TYPE_FIN_PREVUE_CODES = {
    "U": "retablissement_en_evaluation",  # no estimated date
    "D": "retablissement_prevu",  # reliable date
    "P": "retablissement_prevu",  # major outage, delays not guaranteed
    "F": "fin_non_determinee",  # major outage, no dateFinEstimeeMax
    "E": "retablissement_prevu",  # major outage, dateFinEstimeeMax present
    "X": "retablissement_prevu",  # observed near end of major outage
}

# The intervention-status sensor also reuses several info-pannes slugs when the
# interruption is over, postponed, upcoming, or being gradually restored.
STATUT_INTERVENTION_OPTIONS = [
    "aip_a_venir",
    "aip_reportee",
    "equipe_designee",
    "equipe_en_route",
    "evaluation_travaux",
    "fin_non_determinee",
    "reprise_graduelle",
    "retablissement_en_evaluation",
    "retablissement_prevu",
    "service_retabli",
    "travaux_en_cours",
    "travaux_par_priorite",
]

# ---------------------------------------------------------------------------
# Interruption bookkeeping (not sensor states)
# ---------------------------------------------------------------------------

# Codes that indicate a rescheduled AIP (original slot cancelled, new date assigned).
# codeRemarque meanings (observed empirically): "91" changement à la demande d'un
# tiers, "92" annulation d'une AIP, "93" report d'une AIP ("91" confirmed in prod).
AIP_REPORT_CODES = {"91", "93"}
