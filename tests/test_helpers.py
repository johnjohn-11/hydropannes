"""Unit tests for HydroPannesHelperMixin state-transition logic.

These cover the AIP (planned intervention) state machine and outage
selection priority, which are the subtlest parts of the integration.
"""

from __future__ import annotations

from typing import Any

from custom_components.hydropannes.helpers import HydroPannesHelperMixin

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload


class Harness(HydroPannesHelperMixin):
    """Concrete mixin host wired to a fake coordinator."""

    def __init__(self, data: dict[str, Any] | None) -> None:
        self.coordinator = FakeCoordinator(data)


def harness(**payload_kwargs: Any) -> Harness:
    """Build a Harness around a freshly constructed payload."""
    return Harness(make_payload(**payload_kwargs))


# ---------------------------------------------------------------------------
# _is_outage_active
# ---------------------------------------------------------------------------


def test_outage_active_when_etat_n_and_no_date_fin() -> None:
    intr = make_interruption(dateFin=None)
    h = harness(etat="N", interruptions=[intr])
    assert h._is_outage_active(intr) is True


def test_outage_active_when_date_fin_in_future() -> None:
    intr = make_interruption(dateFin=hours_from_now(3))
    h = harness(etat="N", interruptions=[intr])
    assert h._is_outage_active(intr) is True


def test_outage_not_active_when_main_etat_alimente() -> None:
    intr = make_interruption(dateFin=None)
    h = harness(etat="A", interruptions=[intr])
    assert h._is_outage_active(intr) is False


def test_outage_not_active_when_date_fin_in_past() -> None:
    intr = make_interruption(dateFin=hours_from_now(-1))
    h = harness(etat="N", interruptions=[intr])
    assert h._is_outage_active(intr) is False


# ---------------------------------------------------------------------------
# _is_outage_terminated
# ---------------------------------------------------------------------------


def test_outage_terminated_when_date_fin_in_past() -> None:
    intr = make_interruption(dateFin=hours_from_now(-1))
    h = harness(etat="A", interruptions=[intr])
    assert h._is_outage_terminated(intr) is True


def test_outage_not_terminated_when_etat_reportee() -> None:
    # etat "R" (postponed): original dateFin is past but not completed.
    intr = make_interruption(etat="R", dateFin=hours_from_now(-1))
    h = harness(etat="A", interruptions=[intr])
    assert h._is_outage_terminated(intr) is False


def test_aip_reschedule_terminated_uses_date_fin_report() -> None:
    # codeRemarque 91 => rescheduled; termination follows dateFinReport.
    past = make_interruption(
        etat="A",
        interruptionPlanifiee=True,
        codeRemarque="91",
        dateFin=hours_from_now(-48),
        dateFinReport=hours_from_now(-1),
    )
    future = make_interruption(
        etat="A",
        interruptionPlanifiee=True,
        codeRemarque="91",
        dateFin=hours_from_now(-48),
        dateFinReport=hours_from_now(24),
    )
    h = harness(etat="A")
    assert h._is_outage_terminated(past) is True
    assert h._is_outage_terminated(future) is False


def test_integer_code_remarque_is_handled() -> None:
    # HQ sometimes returns codeRemarque as an integer; it must match string codes.
    intr = make_interruption(
        etat="A",
        interruptionPlanifiee=True,
        codeRemarque=91,
        dateFin=hours_from_now(-48),
        dateFinReport=hours_from_now(24),
    )
    h = harness(etat="A")
    assert h._is_aip_reportee(intr) is True
    assert h._is_outage_terminated(intr) is False


# ---------------------------------------------------------------------------
# _is_aip_annulee / _is_aip_reportee
# ---------------------------------------------------------------------------


def test_aip_annulee_via_code_92() -> None:
    intr = make_interruption(interruptionPlanifiee=True, codeRemarque="92")
    h = harness(etat="A")
    assert h._is_aip_annulee(intr) is True


def test_aip_annulee_via_etat_a() -> None:
    intr = make_interruption(interruptionPlanifiee=True, etat="A")
    h = harness(etat="A")
    assert h._is_aip_annulee(intr) is True


def test_reschedule_code_is_not_a_cancellation() -> None:
    # etat "A" + report code means rescheduled, not cancelled.
    intr = make_interruption(interruptionPlanifiee=True, etat="A", codeRemarque="91")
    h = harness(etat="A")
    assert h._is_aip_annulee(intr) is False
    assert h._is_aip_reportee(intr) is True


# ---------------------------------------------------------------------------
# _get_effective_dates
# ---------------------------------------------------------------------------


def test_effective_dates_default_to_debut_fin() -> None:
    debut = hours_from_now(-2)
    fin = hours_from_now(2)
    intr = make_interruption(dateDebut=debut, dateFin=fin)
    h = harness()
    eff_debut, eff_fin = h._get_effective_dates(intr)
    assert eff_debut == h._parse_dt(debut)
    assert eff_fin == h._parse_dt(fin)


def test_effective_dates_use_report_window_for_reschedule() -> None:
    intr = make_interruption(
        etat="A",
        interruptionPlanifiee=True,
        codeRemarque="91",
        dateDebut=hours_from_now(-48),
        dateFin=hours_from_now(-46),
        dateDebutReport=hours_from_now(24),
        dateFinReport=hours_from_now(26),
    )
    h = harness()
    eff_debut, eff_fin = h._get_effective_dates(intr)
    assert eff_debut == h._parse_dt(intr["dateDebutReport"])
    assert eff_fin == h._parse_dt(intr["dateFinReport"])


# ---------------------------------------------------------------------------
# selection priority
# ---------------------------------------------------------------------------


def test_active_outage_selected_over_planned() -> None:
    outage = make_interruption(dateFin=None)
    planned = make_interruption(
        interruptionPlanifiee=True, dateDebut=hours_from_now(48), dateFin=None
    )
    h = harness(etat="N", interruptions=[planned, outage])
    assert h._get_current_interruption() is outage


def test_terminated_outage_yields_to_future_aip() -> None:
    terminated = make_interruption(dateFin=hours_from_now(-1))
    future_aip = make_interruption(
        interruptionPlanifiee=True,
        dateDebut=hours_from_now(24),
        dateFin=hours_from_now(26),
    )
    h = harness(etat="A", interruptions=[terminated, future_aip])
    assert h._get_current_interruption() is future_aip


def test_terminated_outage_kept_when_only_cancelled_aip() -> None:
    terminated = make_interruption(dateFin=hours_from_now(-1))
    cancelled_aip = make_interruption(
        interruptionPlanifiee=True,
        etat="A",
        codeRemarque="92",
        dateDebut=hours_from_now(24),
    )
    h = harness(etat="A", interruptions=[terminated, cancelled_aip])
    assert h._get_current_interruption() is terminated


def test_most_recent_terminated_outage_is_chosen() -> None:
    older = make_interruption(dateFin=hours_from_now(-5))
    newer = make_interruption(dateFin=hours_from_now(-1))
    h = harness(etat="A", interruptions=[older, newer])
    assert h._get_terminated_outage() is newer


def test_no_interruptions_returns_none() -> None:
    h = harness(etat="A", interruptions=[])
    assert h._get_current_interruption() is None


# ---------------------------------------------------------------------------
# _planned_supersedes_terminated
# ---------------------------------------------------------------------------


def test_planned_supersedes_terminated_true_for_future_aip() -> None:
    planned = make_interruption(
        interruptionPlanifiee=True, dateDebut=hours_from_now(24), dateFin=hours_from_now(26)
    )
    h = harness()
    assert h._planned_supersedes_terminated(planned) is True


def test_planned_supersedes_terminated_false_when_none() -> None:
    h = harness()
    assert h._planned_supersedes_terminated(None) is False


def test_planned_supersedes_terminated_false_when_cancelled() -> None:
    planned = make_interruption(interruptionPlanifiee=True, etat="A", codeRemarque="92")
    h = harness()
    assert h._planned_supersedes_terminated(planned) is False


def test_planned_supersedes_terminated_false_when_terminated() -> None:
    planned = make_interruption(interruptionPlanifiee=True, dateFin=hours_from_now(-1))
    h = harness()
    assert h._planned_supersedes_terminated(planned) is False
