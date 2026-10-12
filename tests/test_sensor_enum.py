"""Tests for the enumerated (SensorDeviceClass.ENUM) sensors.

These sensors report language-neutral slugs; the displayed labels come from the translation files. Home Assistant rejects any state outside ``_attr_options``, so the central invariant here is that every state the sensors can produce is declared in their options list.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
import pytest

from custom_components.hydropannes.const import (
    CAUSE_DESCRIPTIONS,
    CAUSE_OPTIONS,
    INFO_PANNES_OPTIONS,
    NIVEAU_URGENCE_OPTIONS,
    RETABLISSEMENT_OPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS,
    STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR,
    STATUT_INTERVENTION_OPTIONS,
)
from custom_components.hydropannes.sensor import (
    HydroPannesCauseSensor,
    HydroPannesInfoPannesSensor,
    HydroPannesNiveauUrgenceSensor,
    HydroPannesRetablissementSensor,
    HydroPannesStatutInterventionSensor,
)

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload

ENUM_SENSORS = [
    pytest.param(HydroPannesInfoPannesSensor, INFO_PANNES_OPTIONS, id="info_pannes"),
    pytest.param(HydroPannesNiveauUrgenceSensor, NIVEAU_URGENCE_OPTIONS, id="niveau_urgence"),
    pytest.param(HydroPannesCauseSensor, CAUSE_OPTIONS, id="cause"),
    pytest.param(
        HydroPannesStatutInterventionSensor, STATUT_INTERVENTION_OPTIONS, id="statut_intervention"
    ),
    pytest.param(HydroPannesRetablissementSensor, RETABLISSEMENT_OPTIONS, id="retablissement"),
]


def build(cls, payload: dict[str, Any] | None):
    """Instantiate a sensor around a payload, bypassing the HA constructor."""
    sensor = cls.__new__(cls)
    sensor.coordinator = FakeCoordinator(payload)
    return sensor


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("cls", "options"), ENUM_SENSORS)
def test_declares_enum_device_class_and_options(cls, options) -> None:
    # Home Assistant's entity metaclass turns _attr_* into class-level properties, so these have to be read from an instance.
    sensor = build(cls, None)
    assert sensor.device_class is SensorDeviceClass.ENUM
    assert sensor.options == options
    # An ENUM sensor must carry neither a unit nor a state class.
    assert sensor.native_unit_of_measurement is None
    assert sensor.state_class is None


@pytest.mark.parametrize(("cls", "options"), ENUM_SENSORS)
def test_options_have_no_duplicates(cls, options) -> None:
    assert len(options) == len(set(options))


# ---------------------------------------------------------------------------
# info_pannes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(make_payload(etat="A", interruptions=[]), "aucune_panne", id="aucune_panne"),
        pytest.param(
            make_payload(etat="N", interruptions=[]), "panne_en_cours", id="panne_sans_interruption"
        ),
        pytest.param(
            make_payload(etat="N", interruptions=[make_interruption(dateFin=None)]),
            "panne_en_cours",
            id="panne_en_cours",
        ),
        pytest.param(
            make_payload(
                etat="N",
                interruptions=[make_interruption(dateFin=None, niveauUrgence="P")],
            ),
            "panne_majeure",
            id="urgence_p",
        ),
        pytest.param(
            make_payload(
                etat="N",
                interruptions=[make_interruption(dateFin=None, niveauUrgence="M")],
            ),
            "panne_majeure",
            id="urgence_m",
        ),
        pytest.param(
            make_payload(
                etat="N",
                interruptions=[make_interruption(dateFin=None)],
                repriseGraduellePossible=True,
            ),
            "reprise_graduelle",
            id="reprise_graduelle",
        ),
        pytest.param(
            make_payload(etat="A", interruptions=[make_interruption(dateFin=hours_from_now(-1))]),
            "service_retabli",
            id="service_retabli",
        ),
        pytest.param(
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(
                        interruptionPlanifiee=True,
                        dateDebut=hours_from_now(24),
                        dateFin=hours_from_now(26),
                    )
                ],
            ),
            "interruption_planifiee_a_venir",
            id="planifiee_a_venir",
        ),
        pytest.param(
            make_payload(
                etat="N",
                interruptions=[
                    make_interruption(interruptionPlanifiee=True, dateFin=hours_from_now(2))
                ],
            ),
            "interruption_planifiee_en_cours",
            id="planifiee_en_cours",
        ),
        pytest.param(
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(interruptionPlanifiee=True, dateFin=hours_from_now(-1))
                ],
            ),
            "interruption_planifiee_terminee",
            id="planifiee_terminee",
        ),
        pytest.param(
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(
                        interruptionPlanifiee=True,
                        etat="A",
                        codeRemarque="92",
                        dateDebut=hours_from_now(24),
                    )
                ],
            ),
            "interruption_planifiee_annulee",
            id="annulee",
        ),
        pytest.param(
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(
                        interruptionPlanifiee=True,
                        etat="R",
                        codeRemarque="93",
                        dateDebut=hours_from_now(-48),
                        dateFin=hours_from_now(-46),
                        dateDebutReport=hours_from_now(24),
                        dateFinReport=hours_from_now(26),
                    )
                ],
            ),
            "interruption_planifiee_reportee",
            id="reportee",
        ),
        pytest.param(
            # Recorded payload: cancelled with code 91 although report dates are present.
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(
                        interruptionPlanifiee=True,
                        etat="A",
                        codeRemarque="91",
                        dateDebut=hours_from_now(24),
                        dateFin=hours_from_now(26),
                        dateDebutReport=hours_from_now(48),
                        dateFinReport=hours_from_now(50),
                    )
                ],
            ),
            "interruption_planifiee_annulee",
            id="annulee_avec_dates_report",
        ),
        pytest.param(
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(
                        interruptionPlanifiee=True,
                        etat="E",
                        dateDebut=hours_from_now(-48),
                        dateFin=hours_from_now(-46),
                        dateDebutDecalage=hours_from_now(24),
                        dateFinDecalage=hours_from_now(26),
                    )
                ],
            ),
            "interruption_planifiee_a_venir",
            id="decalee",
        ),
    ],
)
def test_info_pannes_states(payload, expected) -> None:
    assert build(HydroPannesInfoPannesSensor, payload).native_value == expected


@pytest.mark.parametrize(
    ("etat", "code_remarque", "expected"),
    [
        ("A", "92", {"raison_annulation": "conditions_meteorologiques"}),
        ("R", "93", {"raison_annulation": "autres_travaux_urgents"}),
        ("A", None, {}),
        ("P", "92", {}),  # neither cancelled nor postponed: no reason shown
    ],
)
def test_info_pannes_exposes_raison_annulation(etat, code_remarque, expected) -> None:
    intr = make_interruption(
        interruptionPlanifiee=True,
        etat=etat,
        codeRemarque=code_remarque,
        dateDebut=hours_from_now(24),
        dateFin=hours_from_now(26),
        dateDebutReport=hours_from_now(48),
        dateFinReport=hours_from_now(50),
    )
    payload = make_payload(etat="A", interruptions=[intr])
    assert build(HydroPannesInfoPannesSensor, payload).extra_state_attributes == expected


# ---------------------------------------------------------------------------
# niveau_urgence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("niveau", "expected"),
    [("N", "normal"), ("M", "panne_majeure"), ("P", "panne_majeure"), ("Z", None), (None, None)],
)
def test_niveau_urgence_states(niveau, expected) -> None:
    """An unrecognized code yields None, never a fabricated state."""
    intr = make_interruption(dateFin=None, niveauUrgence=niveau)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesNiveauUrgenceSensor, payload).native_value == expected


# ---------------------------------------------------------------------------
# cause
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("11", "defaillance_equipement"),
        ("13", "bris_equipement"),
        ("21", "foudre"),
        ("52", "dommages_oiseaux"),
        ("53", "dommages_animaux"),
        ("70", "entretien_urgent"),
        ("73", "mesure_protection"),
        (13, "bris_equipement"),  # HQ sometimes returns an integer
        ("58", "indeterminee"),  # absent from the site's mapping too
        ("99", "indeterminee"),  # code the integration does not know
        (None, "indeterminee"),  # HQ reports no code at all
    ],
)
def test_cause_states(code, expected) -> None:
    intr = make_interruption(dateFin=None, codeCause=code)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesCauseSensor, payload).native_value == expected


def test_cause_exposes_raw_code_as_attribute() -> None:
    """Several codes share one slug, so the raw code stays available."""
    intr = make_interruption(dateFin=None, codeCause="14")
    payload = make_payload(etat="N", interruptions=[intr])
    sensor = build(HydroPannesCauseSensor, payload)
    assert sensor.native_value == "bris_equipement"
    assert sensor.extra_state_attributes == {
        "code_cause": "14",
        "description": CAUSE_DESCRIPTIONS["bris_equipement"],
    }


def test_cause_without_code_exposes_only_description() -> None:
    intr = make_interruption(dateFin=None)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesCauseSensor, payload).extra_state_attributes == {
        "description": CAUSE_DESCRIPTIONS["indeterminee"]
    }


def test_every_cause_has_a_description() -> None:
    assert CAUSE_DESCRIPTIONS.keys() == set(CAUSE_OPTIONS)


@pytest.mark.parametrize("cls", [HydroPannesCauseSensor, HydroPannesStatutInterventionSensor])
def test_description_is_not_recorded(cls) -> None:
    assert "description" in cls._unrecorded_attributes


# ---------------------------------------------------------------------------
# statut_intervention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"codeIntervention": "N"}, "evaluation_travaux", id="code_n"),
        pytest.param({"codeIntervention": "A"}, "evaluation_travaux", id="code_a"),
        pytest.param({"codeIntervention": "R"}, "equipe_designee", id="code_r"),
        pytest.param({"codeIntervention": "L"}, "travaux_en_cours", id="code_l"),
        pytest.param(
            {"codeIntervention": "L", "niveauUrgence": "P"},
            "travaux_par_priorite",
            id="code_l_urgence_p",
        ),
        pytest.param(
            {"codeIntervention": "L", "niveauUrgence": "M"},
            "travaux_par_priorite",
            id="code_l_urgence_m",
        ),
        pytest.param({"typeFinPrevue": "U"}, "retablissement_en_evaluation", id="fin_u"),
        pytest.param({"typeFinPrevue": "D"}, "retablissement_prevu", id="fin_d"),
        pytest.param({"typeFinPrevue": "F"}, "fin_non_determinee", id="fin_f"),
        pytest.param(
            {"typeFinPrevue": "ZZ"}, None, id="fin_inconnue"
        ),  # unknown code -> no fabricated state
        pytest.param({}, None, id="vide"),
    ],
)
def test_statut_intervention_states(overrides, expected) -> None:
    intr = make_interruption(dateFin=None, **overrides)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesStatutInterventionSensor, payload).native_value == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"codeIntervention": "N"},
            STATUT_INTERVENTION_DESCRIPTIONS["evaluation_travaux"],
            id="evaluation",
        ),
        pytest.param(
            {"codeIntervention": "N", "niveauUrgence": "P"},
            STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR["evaluation_travaux"],
            id="evaluation_majeure",
        ),
        pytest.param(
            {"codeIntervention": "L", "niveauUrgence": "P"},
            STATUT_INTERVENTION_DESCRIPTIONS["travaux_par_priorite"],
            id="travaux_par_priorite",
        ),
        pytest.param({}, None, id="vide"),  # no state, no description
    ],
)
def test_statut_intervention_description(overrides, expected) -> None:
    intr = make_interruption(dateFin=None, **overrides)
    payload = make_payload(etat="N", interruptions=[intr])
    attrs = build(HydroPannesStatutInterventionSensor, payload).extra_state_attributes
    assert attrs.get("description") == expected


def test_statut_descriptions_name_declared_states() -> None:
    assert STATUT_INTERVENTION_DESCRIPTIONS.keys() <= set(STATUT_INTERVENTION_OPTIONS)
    assert STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR.keys() <= set(STATUT_INTERVENTION_OPTIONS)


def test_statut_intervention_reports_restored_service() -> None:
    intr = make_interruption(dateFin=hours_from_now(-1), codeIntervention="L")
    payload = make_payload(etat="A", interruptions=[intr])
    assert build(HydroPannesStatutInterventionSensor, payload).native_value == "service_retabli"


# ---------------------------------------------------------------------------
# The invariant Home Assistant enforces at runtime
# ---------------------------------------------------------------------------


def _payload_matrix() -> list[dict[str, Any]]:
    """A broad spread of payloads covering the sensors' decision branches."""
    payloads: list[dict[str, Any]] = [
        make_payload(etat="A", interruptions=[]),
        make_payload(etat="N", interruptions=[]),
        make_payload(etat="X", interruptions=[]),
    ]
    extras = (
        {},
        {"niveauUrgence": "P"},
        {"niveauUrgence": "M"},
        {"codeIntervention": "L"},
        {"typeFinPrevue": "F"},
        {"codeCause": "99"},
        {"codeCause": "21"},
        {"dateFinEstimeeMax": hours_from_now(2)},
        {"niveauUrgence": "N"},
    )
    for etat, planned, date_fin, code_remarque, intr_etat, extra in product(
        ("A", "N"),
        (True, False),
        (None, hours_from_now(-1), hours_from_now(3)),
        (None, "91", "92", "93"),
        ("N", "A", "R", "E", "P", "T"),
        extras,
    ):
        intr = make_interruption(
            interruptionPlanifiee=planned,
            etat=intr_etat,
            dateFin=date_fin,
            codeRemarque=code_remarque,
            dateDebutReport=hours_from_now(24),
            dateFinReport=hours_from_now(26),
            **extra,
        )
        payloads.append(make_payload(etat=etat, interruptions=[intr]))
    return payloads


@pytest.mark.parametrize(("cls", "options"), ENUM_SENSORS)
def test_every_produced_state_is_a_declared_option(cls, options) -> None:
    """Home Assistant raises on a state outside options, so none may escape."""
    produced = {build(cls, payload).native_value for payload in _payload_matrix()} - {None}
    assert produced <= set(options), f"{cls.__name__} produced {produced - set(options)}"
    # The matrix is only useful if it actually exercises several states.
    assert len(produced) >= 2


def test_english_descriptions_cover_the_same_states() -> None:
    from custom_components.hydropannes import const

    for name in (
        "CAUSE_DESCRIPTIONS",
        "STATUT_INTERVENTION_DESCRIPTIONS",
        "STATUT_INTERVENTION_DESCRIPTIONS_MAJEUR",
        "RETABLISSEMENT_DESCRIPTIONS",
        "RETABLISSEMENT_DESCRIPTIONS_MAJEUR",
    ):
        assert getattr(const, name).keys() == getattr(const, f"{name}_EN").keys(), name
