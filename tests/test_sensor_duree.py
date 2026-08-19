"""Regression tests for HydroPannesDureeSensor duration calculation.

Guards against the duration sensor reporting negative values for upcoming
planned interventions, and against measuring a rescheduled AIP with its
cancelled original slot instead of its effective window.
"""

from __future__ import annotations

from typing import Any

from custom_components.hydropannes.sensor import HydroPannesDureeSensor

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload


def duree_for(payload: dict[str, Any]) -> int | None:
    """Return the duration sensor's native_value for a given payload.

    The sensor is built with ``__new__`` to bypass the Home Assistant entity
    constructor; ``native_value`` only reads coordinator data via the helper
    mixin, so no further wiring is needed.
    """
    sensor = HydroPannesDureeSensor.__new__(HydroPannesDureeSensor)
    sensor.coordinator = FakeCoordinator(payload)  # type: ignore[assignment]
    return sensor.native_value


def test_ongoing_outage_duration_is_positive() -> None:
    intr = make_interruption(dateDebut=hours_from_now(-2), dateFin=None)
    payload = make_payload(etat="N", interruptions=[intr])
    duree = duree_for(payload)
    assert duree is not None
    # ~2h elapsed, allow slack for test execution time.
    assert 7100 <= duree <= 7300


def test_terminated_outage_duration_uses_window() -> None:
    intr = make_interruption(dateDebut=hours_from_now(-3), dateFin=hours_from_now(-1))
    payload = make_payload(etat="A", interruptions=[intr])
    duree = duree_for(payload)
    assert duree is not None
    # exactly a 2h window.
    assert 7150 <= duree <= 7250


def test_future_planned_intervention_returns_none_not_negative() -> None:
    # Upcoming AIP whose start is in the future and has no dateFin.
    intr = make_interruption(
        interruptionPlanifiee=True,
        etat="P",
        dateDebut=hours_from_now(24),
        dateFin=None,
    )
    payload = make_payload(etat="A", interruptions=[intr])
    assert duree_for(payload) is None


def test_rescheduled_aip_measured_against_report_window() -> None:
    # Cancelled original slot 48h ago; rescheduled to start 1h ago, end in 1h.
    intr = make_interruption(
        interruptionPlanifiee=True,
        etat="A",
        codeRemarque="91",
        dateDebut=hours_from_now(-48),
        dateFin=hours_from_now(-46),
        dateDebutReport=hours_from_now(-1),
        dateFinReport=hours_from_now(1),
    )
    payload = make_payload(etat="A", interruptions=[intr])
    duree = duree_for(payload)
    assert duree is not None
    # 2h effective window, not the ~48h since the cancelled slot.
    assert 7150 <= duree <= 7250


def test_no_interruption_returns_none() -> None:
    payload = make_payload(etat="A", interruptions=[])
    assert duree_for(payload) is None
