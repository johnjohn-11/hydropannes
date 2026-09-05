"""Tests for the enumerated (SensorDeviceClass.ENUM) sensors.

These sensors report language-neutral slugs; the displayed labels come from the
translation files. Home Assistant rejects any state outside ``_attr_options``,
so the central invariant here is that every state the sensors can produce is
declared in their options list.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
import pytest

from custom_components.hydropannes.const import (
    CAUSE_OPTIONS,
    INFO_PANNES_OPTIONS,
    NIVEAU_URGENCE_OPTIONS,
    STATUT_INTERVENTION_OPTIONS,
)
from custom_components.hydropannes.sensor import (
    HydroPannesCauseSensor,
    HydroPannesInfoPannesSensor,
    HydroPannesNiveauUrgenceSensor,
    HydroPannesStatutInterventionSensor,
)

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload

ENUM_SENSORS = [
    (HydroPannesInfoPannesSensor, INFO_PANNES_OPTIONS),
    (HydroPannesNiveauUrgenceSensor, NIVEAU_URGENCE_OPTIONS),
    (HydroPannesCauseSensor, CAUSE_OPTIONS),
    (HydroPannesStatutInterventionSensor, STATUT_INTERVENTION_OPTIONS),
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
    # Home Assistant's entity metaclass turns _attr_* into class-level
    # properties, so these have to be read from an instance.
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
        (make_payload(etat="A", interruptions=[]), "aucune_panne"),
        (make_payload(etat="N", interruptions=[]), "panne_en_cours"),
        (
            make_payload(etat="N", interruptions=[make_interruption(dateFin=None)]),
            "panne_en_cours",
        ),
        (
            make_payload(
                etat="N",
                interruptions=[make_interruption(dateFin=None, niveauUrgence="P")],
            ),
            "panne_majeure",
        ),
        (
            make_payload(
                etat="N",
                interruptions=[make_interruption(dateFin=None)],
                repriseGraduellePossible=True,
            ),
            "reprise_graduelle",
        ),
        (
            make_payload(etat="A", interruptions=[make_interruption(dateFin=hours_from_now(-1))]),
            "service_retabli",
        ),
        (
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
            "aip_a_venir",
        ),
        (
            make_payload(
                etat="N",
                interruptions=[
                    make_interruption(interruptionPlanifiee=True, dateFin=hours_from_now(2))
                ],
            ),
            "aip_en_cours",
        ),
        (
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(interruptionPlanifiee=True, dateFin=hours_from_now(-1))
                ],
            ),
            "aip_terminee",
        ),
        (
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
            "aip_annulee",
        ),
        (
            make_payload(
                etat="A",
                interruptions=[
                    make_interruption(
                        interruptionPlanifiee=True,
                        etat="A",
                        codeRemarque="91",
                        dateDebut=hours_from_now(-48),
                        dateFin=hours_from_now(-46),
                        dateDebutReport=hours_from_now(24),
                        dateFinReport=hours_from_now(26),
                    )
                ],
            ),
            "aip_reportee",
        ),
    ],
)
def test_info_pannes_states(payload, expected) -> None:
    assert build(HydroPannesInfoPannesSensor, payload).native_value == expected


# ---------------------------------------------------------------------------
# niveau_urgence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("niveau", "expected"),
    [("N", "normal"), ("P", "panne_majeure"), ("Z", None), (None, None)],
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
        ("11", "bris_equipement"),
        ("21", "conditions_meteorologiques"),
        ("52", "dommages_animal"),
        (11, "bris_equipement"),  # HQ sometimes returns an integer
        ("99", "inconnue"),  # code the integration does not know yet
        (None, "indeterminee"),  # HQ reports no code at all
    ],
)
def test_cause_states(code, expected) -> None:
    intr = make_interruption(dateFin=None, codeCause=code)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesCauseSensor, payload).native_value == expected


def test_cause_exposes_raw_code_as_attribute() -> None:
    """Several codes share one slug, so the raw code stays available."""
    intr = make_interruption(dateFin=None, codeCause="12")
    payload = make_payload(etat="N", interruptions=[intr])
    sensor = build(HydroPannesCauseSensor, payload)
    assert sensor.native_value == "bris_equipement"
    assert sensor.extra_state_attributes == {"code_cause": "12"}


def test_cause_without_code_exposes_no_attribute() -> None:
    intr = make_interruption(dateFin=None)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesCauseSensor, payload).extra_state_attributes == {}


# ---------------------------------------------------------------------------
# statut_intervention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"codeIntervention": "N"}, "evaluation_travaux"),
        ({"codeIntervention": "A"}, "equipe_designee"),
        ({"codeIntervention": "R"}, "equipe_en_route"),
        ({"codeIntervention": "L"}, "travaux_en_cours"),
        ({"codeIntervention": "L", "niveauUrgence": "P"}, "travaux_par_priorite"),
        ({"typeFinPrevue": "U"}, "retablissement_en_evaluation"),
        ({"typeFinPrevue": "D"}, "retablissement_prevu"),
        ({"typeFinPrevue": "F"}, "fin_non_determinee"),
        ({"typeFinPrevue": "ZZ"}, None),  # unknown code -> no fabricated state
        ({}, None),
    ],
)
def test_statut_intervention_states(overrides, expected) -> None:
    intr = make_interruption(dateFin=None, **overrides)
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesStatutInterventionSensor, payload).native_value == expected


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
    for etat in ("A", "N"):
        for planned in (True, False):
            for date_fin in (None, hours_from_now(-1), hours_from_now(3)):
                for code_remarque in (None, "91", "92", "93"):
                    for intr_etat in ("N", "A", "R", "P", "T"):
                        for extra in (
                            {},
                            {"niveauUrgence": "P"},
                            {"codeIntervention": "L"},
                            {"typeFinPrevue": "F"},
                            {"codeCause": "99"},
                            {"niveauUrgence": "N"},
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
    seen = set()
    for payload in _payload_matrix():
        value = build(cls, payload).native_value
        if value is not None:
            assert value in options, f"{cls.__name__} produced {value!r}, not in options"
            seen.add(value)
    # The matrix is only useful if it actually exercises several states.
    assert len(seen) >= 2
