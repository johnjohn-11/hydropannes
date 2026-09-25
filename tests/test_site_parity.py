"""Tests for the behaviours copied from the Info-pannes site: several simultaneous outages, the restoration step and the rounded address count."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.util import dt as dt_util
import pytest

from custom_components.hydropannes.const import (
    RETABLISSEMENT_DESCRIPTIONS,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR,
)
from custom_components.hydropannes.sensor import (
    HydroPannesNombreClientSensor,
    HydroPannesRetablissementSensor,
)

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload


def build(cls, payload: dict[str, Any] | None):
    """Instantiate a sensor around a payload, bypassing the HA constructor."""
    sensor = cls.__new__(cls)
    sensor.coordinator = FakeCoordinator(payload)
    return sensor


# ---------------------------------------------------------------------------
# Several simultaneous outages
# ---------------------------------------------------------------------------


def test_major_outage_wins_over_later_ending_one() -> None:
    normal = make_interruption(dateFin=None, dateFinEstimeeMax=hours_from_now(10))
    majeure = make_interruption(
        dateFin=None, niveauUrgence="P", dateFinEstimeeMax=hours_from_now(2)
    )
    sensor = build(
        HydroPannesRetablissementSensor, make_payload(etat="N", interruptions=[normal, majeure])
    )
    assert sensor._get_active_outage()["niveauUrgence"] == "P"


def test_latest_ending_outage_wins() -> None:
    early = make_interruption(dateFin=None, dateFinEstimeeMax=hours_from_now(1), nbClient=10)
    late = make_interruption(dateFin=None, dateFinEstimeeMax=hours_from_now(5), nbClient=20)
    sensor = build(
        HydroPannesRetablissementSensor, make_payload(etat="N", interruptions=[early, late])
    )
    assert sensor._get_active_outage()["nbClient"] == 20


def test_overlapping_outage_moves_start_back() -> None:
    kept = make_interruption(
        dateDebut=hours_from_now(-1), dateFin=None, dateFinEstimeeMax=hours_from_now(5)
    )
    earlier = make_interruption(
        dateDebut=hours_from_now(-3), dateFin=None, dateFinEstimeeMax=hours_from_now(2)
    )
    payload = make_payload(etat="N", interruptions=[kept, earlier])
    chosen = build(HydroPannesRetablissementSensor, payload)._get_active_outage()
    assert chosen["dateDebut"] == earlier["dateDebut"]
    # The payload itself is left untouched.
    assert kept["dateDebut"] != earlier["dateDebut"]


def test_non_overlapping_outage_keeps_start() -> None:
    kept = make_interruption(
        dateDebut=hours_from_now(-1), dateFin=None, dateFinEstimeeMax=hours_from_now(5)
    )
    finished_before = make_interruption(dateDebut=hours_from_now(-6), dateFin=hours_from_now(-4))
    payload = make_payload(etat="N", interruptions=[kept, finished_before])
    assert build(HydroPannesRetablissementSensor, payload)._get_active_outage() is kept


# ---------------------------------------------------------------------------
# sensor.*_retablissement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"dateFinEstimeeMax": hours_from_now(2)}, "prevu"),
        ({"dateFinEstimeeMax": hours_from_now(-1)}, "en_revision"),
        ({}, "en_evaluation"),
        ({"codeIntervention": "N"}, "en_evaluation"),
        ({"codeIntervention": "A"}, "en_evaluation"),
        ({"codeIntervention": "R"}, "en_revision"),
        ({"codeIntervention": "L"}, "en_revision"),
        # typeFinPrevue "U" does not prevent the revision, as on the site.
        ({"codeIntervention": "L", "typeFinPrevue": "U"}, "en_revision"),
    ],
)
def test_retablissement_states(overrides, expected) -> None:
    intr = make_interruption(dateFin=None, **overrides)
    sensor = build(HydroPannesRetablissementSensor, make_payload(etat="N", interruptions=[intr]))
    assert sensor.native_value == expected
    assert sensor.extra_state_attributes == {"description": RETABLISSEMENT_DESCRIPTIONS[expected]}


@pytest.mark.parametrize(
    ("minute", "expected"),
    [(0, (14, 0)), (1, (14, 15)), (15, (14, 15)), (31, (14, 45)), (46, (15, 0))],
)
def test_round_up_quarter(minute, expected) -> None:
    sensor = build(HydroPannesRetablissementSensor, None)
    value = datetime(2026, 9, 25, 14, minute, 30, tzinfo=dt_util.UTC)
    rounded = sensor._round_up_quarter(value)
    assert (rounded.hour, rounded.minute, rounded.second) == (*expected, 30)


def test_estimate_just_expired_stays_prevu_until_the_quarter() -> None:
    # One minute ago, but rounded up to a quarter hour that is still ahead of now.
    now = datetime(2026, 9, 25, 14, 20, tzinfo=dt_util.UTC)
    intr = make_interruption(dateFin=None, dateFinEstimeeMax="2026-09-25T14:19:00+00:00")
    sensor = build(HydroPannesRetablissementSensor, make_payload(etat="N", interruptions=[intr]))
    with patch.object(dt_util, "now", return_value=now):
        assert sensor.native_value == "prevu"
    with patch.object(dt_util, "now", return_value=now + timedelta(minutes=11)):
        assert sensor.native_value == "en_revision"


def test_retablissement_major_description() -> None:
    intr = make_interruption(dateFin=None, niveauUrgence="P")
    sensor = build(HydroPannesRetablissementSensor, make_payload(etat="N", interruptions=[intr]))
    assert sensor.extra_state_attributes == {
        "description": RETABLISSEMENT_DESCRIPTIONS_MAJEUR["en_evaluation"]
    }


@pytest.mark.parametrize(
    "payload",
    [
        make_payload(etat="A", interruptions=[]),
        make_payload(etat="A", interruptions=[make_interruption(dateFin=hours_from_now(-1))]),
        make_payload(
            etat="N",
            interruptions=[
                make_interruption(interruptionPlanifiee=True, dateFin=hours_from_now(2))
            ],
        ),
    ],
)
def test_retablissement_none_without_active_unplanned_outage(payload) -> None:
    sensor = build(HydroPannesRetablissementSensor, payload)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


# ---------------------------------------------------------------------------
# sensor.*_adresses_touchees, arrondi attribute
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nb_client", "expected"),
    [
        (1, {"arrondi": "50 ou moins"}),
        (50, {"arrondi": "50 ou moins"}),
        (51, {"arrondi": "100 ou moins"}),
        (499, {"arrondi": "500 ou moins"}),
        (500, {"arrondi": "plus de 500"}),
        (999, {"arrondi": "plus de 500"}),
        (1000, {"arrondi": "plus de 1000"}),
        (2492, {"arrondi": "plus de 1000"}),
        (0, {}),
        (None, {}),
    ],
)
def test_nb_client_arrondi(nb_client, expected) -> None:
    intr = make_interruption(dateFin=None, nbClient=nb_client)
    sensor = build(HydroPannesNombreClientSensor, make_payload(etat="N", interruptions=[intr]))
    assert sensor.extra_state_attributes == expected


def test_new_attributes_are_not_recorded() -> None:
    assert "description" in HydroPannesRetablissementSensor._unrecorded_attributes
    assert "arrondi" in HydroPannesNombreClientSensor._unrecorded_attributes
