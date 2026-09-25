"""Constants for the Hydro-Pannes integration.

Enumerated sensors expose language-neutral slugs as their state, following the Home Assistant ``SensorDeviceClass.ENUM`` convention. The code-to-slug maps live here; the human-readable labels live in ``strings.json`` under ``entity.sensor.<translation_key>.state`` and are translated per language.
"""

DOMAIN = "hydropannes"

CONF_LIEU_CONSO = "lieu_consommation"
CONF_NOM_LIEU = "nom_lieu"
CONF_CODE_POSTAL = "code_postal"
CONF_NUMERO_CIVIQUE = "numero_civique"
CONF_APPARTEMENT = "appartement"

# Bus event fired whenever a location's API payload changes. Carries the full
# payload so users can log or react to changes from their own automations.
EVENT_DATA_CHANGED = f"{DOMAIN}_data_changed"

API_URL = "https://services-bs.solutions.hydroquebec.com/pan/web/api/v1/lieux-conso/etats/{}"

# Address lookup used by the Info-pannes site. Hydro-Québec does not document it, so the config flow keeps manual number entry as a fallback.
SEARCH_URL = "https://services-bs.solutions.hydroquebec.com/pan/web/api/v1/lieux-conso"

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
    "interruption_planifiee_annulee",
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
# Descriptions (the unrecorded "description" attribute)
# ---------------------------------------------------------------------------

# One sentence or two per cause, restating in our own words the explanation the Info-pannes site gives. French only: attribute values are not translated.
CAUSE_DESCRIPTIONS = {
    "defaillance_equipement": "Un équipement du réseau de distribution a mal fonctionné à cause de son usure normale, sans cause externe.",
    "surcharge_reseau": "La demande d'électricité a dépassé ce que l'équipement touché peut supporter.",
    "bris_equipement": "Un équipement a été endommagé ou a mal fonctionné à cause d'un défaut de fabrication d'une de ses pièces.",
    "foudre": "La foudre est tombée pendant un orage, a coupé le service et a pu endommager un équipement du réseau.",
    "precipitations": "De la neige, de la pluie ou du verglas a coupé le service et a pu endommager un équipement du réseau.",
    "sinistre_naturel": "Un phénomène naturel, comme une inondation, un glissement de terrain, de l'érosion, un séisme ou des glaces, a touché le réseau.",
    "vents_violents": "Des vents forts ont coupé le service et ont pu endommager un équipement du réseau.",
    "temperature_extreme": "Une chaleur ou un froid extrême a coupé le service et a pu endommager un équipement du réseau.",
    "accident_ou_incident": "Un événement imprévu est survenu sur le réseau, par exemple une erreur pendant l'essai d'un équipement ou une isolation abîmée par des produits chimiques ou du sel.",
    "usure_materiel": "Une pièce du réseau s'est détériorée avec le temps, la pourriture ou une réaction chimique, au point de briser ou de nuire au fonctionnement de l'équipement.",
    "incendie_ou_fuite_gaz": "Un incendie, une fuite de gaz ou un autre événement a amené les autorités à demander d'urgence la coupure du service dans le secteur.",
    "contact_accidentel": "Une personne ou un objet a touché par accident un équipement du réseau.",
    "securite_publique": "Les autorités ont demandé une coupure d'urgence pour protéger le public ou le personnel.",
    "dommages_vegetation": "Un arbre ou une branche, cassé, plié ou non élagué, a touché un équipement du réseau et l'a endommagé.",
    "dommages_oiseaux": "Un oiseau a touché un équipement du réseau et causé un court-circuit ou une mise à la terre.",
    "dommages_animaux": "Un animal autre qu'un oiseau, comme un écureuil ou un rongeur, a touché un équipement du réseau et causé un court-circuit ou une mise à la terre.",
    "collision_poteau": "Un véhicule a heurté un poteau ou un autre équipement du réseau.",
    "entretien_urgent": "Hydro-Québec a coupé le service pour faire d'urgence, en toute sécurité, des travaux d'entretien, de réparation ou de modification du réseau.",
    "amelioration_entretien_reseau": "Hydro-Québec a coupé le service pour faire, en toute sécurité, des travaux d'entretien, de réparation ou de modification du réseau.",
    "securite_travaux": "Le service est coupé pour protéger le public pendant des travaux, comme le déplacement d'une maison ou des travaux faits par d'autres.",
    "mesure_protection": "Hydro-Québec a coupé le service d'urgence pour éviter des bris importants qui pourraient causer une panne majeure.",
    "travaux_vegetation_elagage": "Le service est coupé pour permettre d'abattre ou d'élaguer des arbres près du réseau en toute sécurité.",
    "indeterminee": "L'origine de l'interruption n'est pas encore connue.",
}

# Same idea for the intervention steps. States without an entry expose no description.
STATUT_INTERVENTION_DESCRIPTIONS = {
    "evaluation_travaux": "Hydro-Québec tente de rétablir le service à distance, évalue les dommages et les travaux à faire, puis envoie les équipes selon les priorités. La durée de cette évaluation varie d'une panne à l'autre.",
    "equipe_designee": "Une équipe est chargée des travaux. Elle peut s'occuper de plusieurs pannes à la fois et être envoyée ailleurs si une panne plus urgente survient.",
    "travaux_en_cours": "L'équipe constate l'ampleur des travaux une fois sur place. L'heure de rétablissement peut changer selon ce qu'elle observe.",
    "travaux_par_priorite": "Pendant une panne majeure, les travaux suivent un ordre de priorité : les dangers signalés au 911, les hôpitaux et les services d'urgence passent en premier.",
    "retablissement_en_evaluation": "Il faut de 15 à 20 minutes pour estimer le temps nécessaire au rétablissement du service.",
    "retablissement_prevu": "Hydro-Québec estime l'heure de rétablissement avec l'information dont elle dispose et peut l'ajuster selon ce que l'équipe constate sur place.",
    "fin_non_determinee": "Quand un événement cause beaucoup de pannes, l'heure de rétablissement peut prendre plus de temps à estimer.",
    "reprise_graduelle": "Hydro-Québec rétablit le service graduellement dans le secteur pour protéger ses équipements et éviter d'autres pannes. Le courant peut revenir quelques minutes, puis être coupé de nouveau pendant 30 minutes à 5 heures.",
    "service_retabli": "Si le courant n'est toujours pas revenu, il faut signaler la panne de nouveau à Hydro-Québec.",
}

# Overrides STATUT_INTERVENTION_DESCRIPTIONS during a major outage (niveauUrgence in NIVEAU_URGENCE_MAJEURS).
STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR = {
    "evaluation_travaux": "Hydro-Québec tente de rétablir le service à distance, évalue les dommages et envoie les équipes selon les priorités. Pendant une panne majeure, cette évaluation peut être plus longue.",
    "retablissement_en_evaluation": STATUT_INTERVENTION_DESCRIPTIONS["fin_non_determinee"],
}

# ---------------------------------------------------------------------------
# sensor.*_retablissement
# ---------------------------------------------------------------------------

# The restoration step of the Info-pannes outage tracker, separate from the intervention step.
RETABLISSEMENT_OPTIONS = ["en_evaluation", "prevu", "en_revision"]

RETABLISSEMENT_DESCRIPTIONS = {
    "en_evaluation": STATUT_INTERVENTION_DESCRIPTIONS["retablissement_en_evaluation"],
    "prevu": STATUT_INTERVENTION_DESCRIPTIONS["retablissement_prevu"],
    "en_revision": "L'heure de rétablissement prévue est dépassée ou doit être revue selon les nouveaux renseignements sur la panne.",
}

RETABLISSEMENT_DESCRIPTIONS_MAJEUR = {
    "en_evaluation": STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR["retablissement_en_evaluation"],
}

# ---------------------------------------------------------------------------
# Interruption bookkeeping (not sensor states)
# ---------------------------------------------------------------------------

# Planned interruption etat values, as the Info-pannes site names them. The etat alone says whether a planned interruption is confirmed, postponed, shifted or cancelled.
ETAT_PLANIFIE_REPORTE = "R"  # new window in dateDebutReport/dateFinReport
ETAT_PLANIFIE_DECALE = "E"  # new window in dateDebutDecalage/dateFinDecalage
ETAT_PLANIFIE_ANNULE = "A"

# codeRemarque → raison_annulation slug, as the Info-pannes site maps them. It is only the reason shown next to a cancelled or postponed interruption, never its state: dateDebutReport is present even on confirmed ones, and a cancellation with code 91 was followed by no new interruption in recorded payloads. Any other code is "Modification de la planification des travaux" on the site.
RAISON_ANNULATION_CODES = {
    "45": "travaux_deja_realises",
    "50": "demande_tiers",
    "60": "demande_tiers",
    "91": "demande_tiers",
    "92": "conditions_meteorologiques",
    "93": "autres_travaux_urgents",
    "94": "autres_travaux_urgents",
}
RAISON_ANNULATION_DEFAUT = "planification_modifiee"

# dureePrevu (minutes) from which the Info-pannes site warns that a planned interruption may end with a gradual restoration.
GRAP_DUREE_PREVUE_MINUTES = 480
