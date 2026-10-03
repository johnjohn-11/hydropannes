"""Tests for the behaviours copied from the Info-pannes site: several simultaneous outages, the restoration step, the rounded address count and planned interruptions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.util import dt as dt_util
import pytest

from custom_components.hydropannes.binary_sensor import (
    HydroPannesEtatServiceBinarySensor,
    HydroPannesInterventionPlanifieeBinarySensor,
)
from custom_components.hydropannes.const import (
    RETABLISSEMENT_DESCRIPTIONS,
    RETABLISSEMENT_DESCRIPTIONS_MAJEUR,
)
from custom_components.hydropannes.model import round_up_quarter
from custom_components.hydropannes.sensor import (
    HydroPannesAdressesToucheesSensor,
    HydroPannesDateFinSensor,
    HydroPannesInfoPannesSensor,
    HydroPannesRetablissementSensor,
    HydroPannesStatutInterventionSensor,
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
    assert sensor._etat.panne_active["niveauUrgence"] == "P"


def test_latest_ending_outage_wins() -> None:
    early = make_interruption(dateFin=None, dateFinEstimeeMax=hours_from_now(1), nbClient=10)
    late = make_interruption(dateFin=None, dateFinEstimeeMax=hours_from_now(5), nbClient=20)
    sensor = build(
        HydroPannesRetablissementSensor, make_payload(etat="N", interruptions=[early, late])
    )
    assert sensor._etat.panne_active["nbClient"] == 20


def test_overlapping_outage_moves_start_back() -> None:
    kept = make_interruption(
        dateDebut=hours_from_now(-1), dateFin=None, dateFinEstimeeMax=hours_from_now(5)
    )
    earlier = make_interruption(
        dateDebut=hours_from_now(-3), dateFin=None, dateFinEstimeeMax=hours_from_now(2)
    )
    payload = make_payload(etat="N", interruptions=[kept, earlier])
    chosen = build(HydroPannesRetablissementSensor, payload)._etat.panne_active
    assert chosen["dateDebut"] == earlier["dateDebut"]
    # The payload itself is left untouched.
    assert kept["dateDebut"] != earlier["dateDebut"]


def test_non_overlapping_outage_keeps_start() -> None:
    kept = make_interruption(
        dateDebut=hours_from_now(-1), dateFin=None, dateFinEstimeeMax=hours_from_now(5)
    )
    finished_before = make_interruption(dateDebut=hours_from_now(-6), dateFin=hours_from_now(-4))
    payload = make_payload(etat="N", interruptions=[kept, finished_before])
    assert build(HydroPannesRetablissementSensor, payload)._etat.panne_active is kept


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
    build(HydroPannesRetablissementSensor, None)
    value = datetime(2026, 9, 25, 14, minute, 30, tzinfo=dt_util.UTC)
    rounded = round_up_quarter(value)
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
    ],
)
def test_retablissement_none_without_outage_or_planned_in_progress(payload) -> None:
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
    sensor = build(HydroPannesAdressesToucheesSensor, make_payload(etat="N", interruptions=[intr]))
    assert sensor.extra_state_attributes == expected


def test_new_attributes_are_not_recorded() -> None:
    assert "description" in HydroPannesRetablissementSensor._unrecorded_attributes
    assert "arrondi" in HydroPannesAdressesToucheesSensor._unrecorded_attributes


# ---------------------------------------------------------------------------
# Planned interruption in progress
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("date_fin", "statut", "retablissement"),
    [
        (hours_from_now(2), "retablissement_prevu", "prevu"),
        (None, "travaux_en_cours", None),
    ],
)
def test_planned_in_progress_steps(date_fin, statut, retablissement) -> None:
    # Recorded planned interruptions carry no codeIntervention nor typeFinPrevue.
    intr = make_interruption(
        interruptionPlanifiee=True, etat="P", dateDebut=hours_from_now(-1), dateFin=date_fin
    )
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesStatutInterventionSensor, payload).native_value == statut
    assert build(HydroPannesRetablissementSensor, payload).native_value == retablissement


def test_planned_in_progress_never_under_review() -> None:
    # The site's planned-interruption tracker has no revision step, even past the estimate.
    intr = make_interruption(
        interruptionPlanifiee=True,
        dateDebut=hours_from_now(-3),
        dateFin=hours_from_now(1),
        dateFinEstimeeMax=hours_from_now(-1),
    )
    payload = make_payload(etat="N", interruptions=[intr])
    assert build(HydroPannesRetablissementSensor, payload).native_value == "prevu"


def test_upcoming_planned_has_no_restoration_step() -> None:
    intr = make_interruption(
        interruptionPlanifiee=True, dateDebut=hours_from_now(24), dateFin=hours_from_now(26)
    )
    payload = make_payload(etat="A", interruptions=[intr])
    assert (
        build(HydroPannesStatutInterventionSensor, payload).native_value
        == "interruption_planifiee_a_venir"
    )
    assert build(HydroPannesRetablissementSensor, payload).native_value is None


# ---------------------------------------------------------------------------
# Other upcoming planned interruptions
# ---------------------------------------------------------------------------


def _planned(debut: float, **overrides: Any) -> dict[str, Any]:
    fields = {
        "interruptionPlanifiee": True,
        "etat": "P",
        "dateDebut": hours_from_now(debut),
        "dateFin": hours_from_now(debut + 4),
    }
    return make_interruption(**{**fields, **overrides})


def test_planned_sensor_lists_the_others_nearest_first() -> None:
    later = _planned(72, dureePrevu=240)
    nearest = _planned(24, dureePrevu=270)
    long_one = _planned(48, dureePrevu=480)
    cancelled = _planned(12, etat="A")
    payload = make_payload(etat="A", interruptions=[later, nearest, long_one, cancelled])
    attrs = build(HydroPannesInterventionPlanifieeBinarySensor, payload).extra_state_attributes
    assert attrs["dureePrevu"] == 270  # the nearest non-cancelled one
    suivantes = attrs["interruptions_suivantes"]
    assert [s["duree_prevue"] for s in suivantes] == [480, 240]
    assert suivantes[0]["reprise_graduelle_possible"] is True
    assert "reprise_graduelle_possible" not in suivantes[1]
    assert (
        suivantes[0]["debut"]
        == dt_util.as_local(dt_util.parse_datetime(long_one["dateDebut"])).isoformat()
    )


def test_planned_sensor_without_others_has_no_list() -> None:
    payload = make_payload(etat="A", interruptions=[_planned(24, dureePrevu=270)])
    attrs = build(HydroPannesInterventionPlanifieeBinarySensor, payload).extra_state_attributes
    assert "interruptions_suivantes" not in attrs


def test_info_pannes_follows_the_nearest_planned() -> None:
    later = _planned(72)
    nearest = _planned(
        24, etat="R", dateDebutReport=hours_from_now(30), dateFinReport=hours_from_now(34)
    )
    payload = make_payload(etat="A", interruptions=[later, nearest])
    sensor = build(HydroPannesInfoPannesSensor, payload)
    assert sensor.native_value == "interruption_planifiee_reportee"


# ---------------------------------------------------------------------------
# Intervention status of a planned interruption that is not under way
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"etat": "P"}, "interruption_planifiee_a_venir"),
        ({"etat": "E", "dateDebutDecalage": hours_from_now(30)}, "interruption_planifiee_a_venir"),
        (
            {
                "etat": "R",
                "dateDebutReport": hours_from_now(30),
                "dateFinReport": hours_from_now(34),
            },
            "interruption_planifiee_reportee",
        ),
        ({"etat": "A", "codeRemarque": "91"}, "interruption_planifiee_annulee"),
    ],
)
def test_statut_of_planned_not_under_way(overrides, expected) -> None:
    payload = make_payload(etat="A", interruptions=[_planned(24, **overrides)])
    assert build(HydroPannesStatutInterventionSensor, payload).native_value == expected


def test_cancelled_planned_stays_cancelled_once_its_slot_is_past() -> None:
    payload = make_payload(etat="A", interruptions=[_planned(-10, etat="A")])
    assert (
        build(HydroPannesStatutInterventionSensor, payload).native_value
        == "interruption_planifiee_annulee"
    )


# ---------------------------------------------------------------------------
# Root etat and interruptions disagreeing (the site's nonSynchronise)
# ---------------------------------------------------------------------------


def test_fed_root_with_outage_under_way_shows_outage_without_details() -> None:
    """Replays real payloads: root etat "A" while an unplanned interruption "C" without dateFin is listed."""
    payload = make_payload(etat="A", interruptions=[make_interruption(etat="C", dateFin=None)])
    assert build(HydroPannesInfoPannesSensor, payload).native_value == "panne_en_cours"
    assert build(HydroPannesStatutInterventionSensor, payload).native_value is None
    assert build(HydroPannesRetablissementSensor, payload).native_value is None
    assert build(HydroPannesEtatServiceBinarySensor, payload).is_on is True


def test_unfed_root_with_only_terminated_outages_shows_outage_under_way() -> None:
    """Replays real payloads: root etat "N" while the only interruption is "T" with a past dateFin."""
    payload = make_payload(
        etat="N", interruptions=[make_interruption(etat="T", dateFin=hours_from_now(-10))]
    )
    assert build(HydroPannesInfoPannesSensor, payload).native_value == "panne_en_cours"
    assert build(HydroPannesStatutInterventionSensor, payload).native_value is None
    assert build(HydroPannesEtatServiceBinarySensor, payload).is_on is True


def test_terminated_outage_with_fed_root_is_restored() -> None:
    payload = make_payload(
        etat="A", interruptions=[make_interruption(etat="T", dateFin=hours_from_now(-1))]
    )
    assert build(HydroPannesInfoPannesSensor, payload).native_value == "service_retabli"
    assert build(HydroPannesEtatServiceBinarySensor, payload).is_on is False


def _iso_local(value: str) -> str:
    return dt_util.as_local(dt_util.parse_datetime(value)).isoformat()


def test_planned_sensor_lists_the_fallback_slot() -> None:
    """Replays a real payload: a confirmed interruption carries the slot the site lists under "En cas de report"."""
    intr = _planned(
        24,
        dureePrevu=270,
        dateDebutReport=hours_from_now(24 * 14),
        dateFinReport=hours_from_now(24 * 14 + 4),
    )
    attrs = build(
        HydroPannesInterventionPlanifieeBinarySensor, make_payload(etat="A", interruptions=[intr])
    ).extra_state_attributes
    assert attrs["debut"] == _iso_local(intr["dateDebut"])
    assert attrs["fin"] == _iso_local(intr["dateFin"])
    assert attrs["report_debut"] == _iso_local(intr["dateDebutReport"])
    assert attrs["report_fin"] == _iso_local(intr["dateFinReport"])
    assert "fin_au_plus_tard" not in attrs


def test_postponed_planned_has_no_fallback_slot() -> None:
    intr = _planned(
        -100,
        etat="R",
        dateDebutReport=hours_from_now(24),
        dateFinReport=hours_from_now(28),
    )
    attrs = build(
        HydroPannesInterventionPlanifieeBinarySensor, make_payload(etat="A", interruptions=[intr])
    ).extra_state_attributes
    assert attrs["debut"] == _iso_local(intr["dateDebutReport"])
    assert "report_debut" not in attrs


def test_long_planned_ends_within_five_hours() -> None:
    intr = _planned(24, dureePrevu=480)
    attrs = build(
        HydroPannesInterventionPlanifieeBinarySensor, make_payload(etat="A", interruptions=[intr])
    ).extra_state_attributes
    fin = dt_util.as_local(dt_util.parse_datetime(intr["dateFin"]))
    assert attrs["fin_au_plus_tard"] == (fin + timedelta(hours=5)).isoformat()
    assert attrs["reprise_graduelle_possible"] is True


def test_fin_estimee_min_exposed_for_a_range() -> None:
    intr = make_interruption(
        dateFin=None, dateFinEstimeeMin=hours_from_now(1), dateFinEstimeeMax=hours_from_now(3)
    )
    sensor = build(HydroPannesDateFinSensor, make_payload(etat="N", interruptions=[intr]))
    assert sensor.native_value == dt_util.as_local(
        dt_util.parse_datetime(intr["dateFinEstimeeMax"])
    )
    assert sensor.extra_state_attributes == {
        "fin_estimee_min": _iso_local(intr["dateFinEstimeeMin"])
    }


@pytest.mark.parametrize("same_as_max", [False, True])
def test_fin_estimee_min_absent_without_a_range(same_as_max) -> None:
    fin_max = hours_from_now(3)
    intr = make_interruption(
        dateFin=None,
        dateFinEstimeeMin=fin_max if same_as_max else None,
        dateFinEstimeeMax=fin_max,
    )
    sensor = build(HydroPannesDateFinSensor, make_payload(etat="N", interruptions=[intr]))
    assert sensor.extra_state_attributes == {}


@pytest.mark.parametrize(
    ("nb_client", "expected"), [(120, "150 or less"), (600, "Over 500"), (1500, "Over 1000")]
)
def test_nb_client_arrondi_english(nb_client, expected) -> None:
    from custom_components.hydropannes.sensor import _nb_client_arrondi

    assert _nb_client_arrondi(nb_client, english=True) == expected
