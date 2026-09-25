"""Constants for the Hydro-Pannes integration.

Enumerated sensors expose language-neutral slugs as their state, following the Home Assistant ``SensorDeviceClass.ENUM`` convention. The code-to-slug maps live here; the human-readable labels live in ``strings.json`` under ``entity.sensor.<translation_key>.state`` and are translated per language.
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

# Every state the info-pannes sensor can report. A value outside this list is rejected by Home Assistant, so the sensor returns None rather than inventing a state for data it does not recognize.
INFO_PANNES_OPTIONS = [
    "aucune_panne",
    "panne_en_cours",
    "panne_majeure",
    "reprise_graduelle",
    "service_retabli",
    "interruption_planifiee_en_cours",
    "interruption_planifiee_a_venir",
    "interruption_planifiee_terminee",
    "interruption_planifiee_annulee",
    "interruption_planifiee_reportee",
]

# ---------------------------------------------------------------------------
# sensor.*_niveau_urgence
# ---------------------------------------------------------------------------

# The Info-pannes site names "M" panne majeure and "P" PURS, and handles both the same way. Only "N" and "P" have been observed in the API so far.
NIVEAU_URGENCE_CODES = {
    "N": "normal",
    "M": "panne_majeure",
    "P": "panne_majeure",
}

NIVEAU_URGENCE_MAJEURS = {"M", "P"}

NIVEAU_URGENCE_OPTIONS = ["normal", "panne_majeure"]

# ---------------------------------------------------------------------------
# sensor.*_cause
# ---------------------------------------------------------------------------

# codeCause → slug, as the Info-pannes site maps them. Any other code, 58 included, is "Indéterminée" on the site too. The raw code is exposed as the ``code_cause`` attribute so no information is lost by mapping several codes onto one slug.
CAUSE_CODES = {
    "11": "defaillance_equipement",
    "12": "surcharge_reseau",
    "13": "bris_equipement",
    "14": "bris_equipement",
    "15": "bris_equipement",
    "72": "bris_equipement",
    "79": "bris_equipement",
    "21": "foudre",
    "22": "precipitations",
    "24": "sinistre_naturel",
    "25": "vents_violents",
    "26": "temperature_extreme",
    "31": "accident_ou_incident",
    "32": "accident_ou_incident",
    "41": "accident_ou_incident",
    "43": "accident_ou_incident",
    "56": "accident_ou_incident",
    "57": "accident_ou_incident",
    "33": "usure_materiel",
    "34": "incendie_ou_fuite_gaz",
    "42": "contact_accidentel",
    "55": "contact_accidentel",
    "44": "securite_publique",
    "51": "dommages_vegetation",
    "52": "dommages_oiseaux",
    "53": "dommages_animaux",
    "54": "collision_poteau",
    "60": "entretien_urgent",
    "70": "entretien_urgent",
    "61": "amelioration_entretien_reseau",
    "62": "amelioration_entretien_reseau",
    "63": "amelioration_entretien_reseau",
    "64": "amelioration_entretien_reseau",
    "65": "amelioration_entretien_reseau",
    "67": "amelioration_entretien_reseau",
    "68": "amelioration_entretien_reseau",
    "69": "amelioration_entretien_reseau",
    "71": "amelioration_entretien_reseau",
    "66": "securite_travaux",
    "73": "mesure_protection",
    "74": "mesure_protection",
    "77": "travaux_vegetation_elagage",
    "78": "travaux_vegetation_elagage",
}

CAUSE_OPTIONS = [
    "accident_ou_incident",
    "amelioration_entretien_reseau",
    "bris_equipement",
    "collision_poteau",
    "contact_accidentel",
    "defaillance_equipement",
    "dommages_animaux",
    "dommages_oiseaux",
    "dommages_vegetation",
    "entretien_urgent",
    "foudre",
    "incendie_ou_fuite_gaz",
    "indeterminee",
    "mesure_protection",
    "precipitations",
    "securite_publique",
    "securite_travaux",
    "sinistre_naturel",
    "surcharge_reseau",
    "temperature_extreme",
    "travaux_vegetation_elagage",
    "usure_materiel",
    "vents_violents",
]

# ---------------------------------------------------------------------------
# sensor.*_statut_intervention
# ---------------------------------------------------------------------------

# codeIntervention → slug, following the Info-pannes steps: N (aucune) and A (attribuée) are both shown as the assessment step, R (en route) as "Équipe désignée".
INTERVENTION_CODES = {
    "N": "evaluation_travaux",
    "A": "evaluation_travaux",
    "R": "equipe_designee",
    "L": "travaux_en_cours",
}

# Overrides INTERVENTION_CODES["L"] for major outages (niveauUrgence in NIVEAU_URGENCE_MAJEURS).
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

# The intervention-status sensor also reuses several info-pannes slugs when the interruption is over, postponed, upcoming, or being gradually restored.
STATUT_INTERVENTION_OPTIONS = [
    "interruption_planifiee_a_venir",
    "interruption_planifiee_reportee",
    "equipe_designee",
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

# Codes that indicate a rescheduled planned interruption (original slot cancelled, new date assigned).
# codeRemarque meanings (observed empirically): "91" changement à la demande d'un
# tiers, "92" annulation d'une interruption planifiée, "93" report d'une interruption planifiée ("91" confirmed in prod).
PLANNED_RESCHEDULE_CODES = {"91", "93"}
