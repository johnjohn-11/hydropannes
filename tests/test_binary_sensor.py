"""Tests for the planned-intervention binary sensor."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.hydropannes.binary_sensor import (
    HydroPannesInterventionPlanifieeBinarySensor,
)

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload


def build(payload: dict[str, Any] | None) -> HydroPannesInterventionPlanifieeBinarySensor:
    """Instantiate the sensor around a payload, bypassing the HA constructor."""
    sensor = HydroPannesInterventionPlanifieeBinarySensor.__new__(
        HydroPannesInterventionPlanifieeBinarySensor
    )
    sensor.coordinator = FakeCoordinator(payload)
    return sensor


@pytest.mark.parametrize(
    ("etat", "expected"),
    [
        ("P", True),
        ("R", True),
        ("E", True),
        ("A", False),  # cancelled, even with a future window
    ],
)
def test_planned_intervention_on_unless_cancelled(etat, expected) -> None:
    intr = make_interruption(
        interruptionPlanifiee=True,
        etat=etat,
        dateDebut=hours_from_now(24),
        dateFin=hours_from_now(26),
        dateDebutReport=hours_from_now(48),
        dateFinReport=hours_from_now(50),
        dateDebutDecalage=hours_from_now(48),
        dateFinDecalage=hours_from_now(50),
    )
    sensor = build(make_payload(etat="A", interruptions=[intr]))
    assert sensor.is_on is expected
    assert bool(sensor.extra_state_attributes) is expected


def test_planned_intervention_exposes_shifted_window() -> None:
    intr = make_interruption(
        interruptionPlanifiee=True,
        etat="E",
        dateDebut=hours_from_now(24),
        dateFin=hours_from_now(26),
        dateDebutDecalage=hours_from_now(30),
        dateFinDecalage=hours_from_now(32),
    )
    attrs = build(make_payload(etat="A", interruptions=[intr])).extra_state_attributes
    assert {"dateDebutDecalage", "dateFinDecalage"} <= attrs.keys()
