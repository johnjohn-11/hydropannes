"""Unit tests for HydroPannesHelperMixin state-transition logic.

These cover the planned-interruption state machine and outage
selection priority, which are the subtlest parts of the integration.
"""

from __future__ import annotations

from typing import Any

import pytest

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


def test_outage_not_terminated_when_etat_reportee_without_new_end() -> None:
    # etat "R" (postponed): the original dateFin is the abandoned slot.
    intr = make_interruption(etat="R", dateFin=hours_from_now(-1))
    h = harness(etat="A", interruptions=[intr])
    assert h._is_outage_terminated(intr) is False


@pytest.mark.parametrize(("etat", "suffix"), [("R", "Report"), ("E", "Decalage")])
def test_postponed_or_shifted_terminated_follows_new_end(etat, suffix) -> None:
    def planned(new_end: str) -> dict[str, Any]:
        return make_interruption(
            etat=etat,
            interruptionPlanifiee=True,
            dateFin=hours_from_now(-48),
            **{f"dateFin{suffix}": new_end},
        )

    h = harness(etat="A")
    assert h._is_outage_terminated(planned(hours_from_now(-1))) is True
    assert h._is_outage_terminated(planned(hours_from_now(24))) is False


# ---------------------------------------------------------------------------
# _is_planned_cancelled / _is_planned_postponed / _raison_annulation
# ---------------------------------------------------------------------------


def test_planned_cancelled_via_etat_a() -> None:
    intr = make_interruption(interruptionPlanifiee=True, etat="A")
    h = harness(etat="A")
    assert h._is_planned_cancelled(intr) is True


def test_code_remarque_alone_is_not_a_state() -> None:
    # codeRemarque is only the reason: a confirmed interruption carrying 92 stays confirmed.
    intr = make_interruption(interruptionPlanifiee=True, etat="P", codeRemarque="92")
    h = harness(etat="A")
    assert h._is_planned_cancelled(intr) is False
    assert h._is_planned_postponed(intr) is False


def test_cancellation_with_report_dates_stays_cancelled() -> None:
    # Recorded payload: etat "A" with code 91 and report dates, followed by no new interruption.
    intr = make_interruption(
        interruptionPlanifiee=True,
        etat="A",
        codeRemarque="91",
        dateDebutReport=hours_from_now(24),
        dateFinReport=hours_from_now(26),
    )
    h = harness(etat="A")
    assert h._is_planned_cancelled(intr) is True
    assert h._is_planned_postponed(intr) is False


def test_planned_postponed_via_etat_r() -> None:
    intr = make_interruption(interruptionPlanifiee=True, etat="R", codeRemarque="93")
    h = harness(etat="A")
    assert h._is_planned_postponed(intr) is True
    assert h._is_planned_cancelled(intr) is False


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("45", "travaux_deja_realises"),
        ("91", "demande_tiers"),
        (91, "demande_tiers"),  # HQ sometimes returns an integer
        ("92", "conditions_meteorologiques"),
        ("93", "autres_travaux_urgents"),
        ("40", "planification_modifiee"),  # any other code
        ("", None),
        (None, None),
    ],
)
def test_raison_annulation(code, expected) -> None:
    intr = make_interruption(interruptionPlanifiee=True, etat="A", codeRemarque=code)
    assert harness()._raison_annulation(intr) == expected


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


@pytest.mark.parametrize(("etat", "suffix"), [("R", "Report"), ("E", "Decalage")])
def test_effective_dates_use_new_window(etat, suffix) -> None:
    intr = make_interruption(
        etat=etat,
        interruptionPlanifiee=True,
        dateDebut=hours_from_now(-48),
        dateFin=hours_from_now(-46),
        **{f"dateDebut{suffix}": hours_from_now(24), f"dateFin{suffix}": hours_from_now(26)},
    )
    h = harness()
    eff_debut, eff_fin = h._get_effective_dates(intr)
    assert eff_debut == h._parse_dt(intr[f"dateDebut{suffix}"])
    assert eff_fin == h._parse_dt(intr[f"dateFin{suffix}"])


@pytest.mark.parametrize("etat", ["P", "A"])
def test_effective_dates_ignore_report_dates_unless_postponed(etat) -> None:
    # Recorded payloads carry dateDebutReport on confirmed and cancelled interruptions too.
    intr = make_interruption(
        etat=etat,
        interruptionPlanifiee=True,
        dateDebut=hours_from_now(24),
        dateFin=hours_from_now(26),
        dateDebutReport=hours_from_now(48),
        dateFinReport=hours_from_now(50),
    )
    h = harness()
    assert h._get_effective_dates(intr) == (
        h._parse_dt(intr["dateDebut"]),
        h._parse_dt(intr["dateFin"]),
    )


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


def test_terminated_outage_yields_to_future_planned() -> None:
    terminated = make_interruption(dateFin=hours_from_now(-1))
    future_planned = make_interruption(
        interruptionPlanifiee=True,
        dateDebut=hours_from_now(24),
        dateFin=hours_from_now(26),
    )
    h = harness(etat="A", interruptions=[terminated, future_planned])
    assert h._get_current_interruption() is future_planned


def test_terminated_outage_kept_when_only_cancelled_planned() -> None:
    terminated = make_interruption(dateFin=hours_from_now(-1))
    cancelled_planned = make_interruption(
        interruptionPlanifiee=True,
        etat="A",
        codeRemarque="92",
        dateDebut=hours_from_now(24),
    )
    h = harness(etat="A", interruptions=[terminated, cancelled_planned])
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


def test_planned_supersedes_terminated_true_for_future_planned() -> None:
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


# ---------------------------------------------------------------------------
# _is_reprise_graduelle
# ---------------------------------------------------------------------------


def test_reprise_graduelle_read_from_payload_root() -> None:
    intr = make_interruption(dateFin=None)
    h = harness(etat="N", interruptions=[intr], repriseGraduellePossible=True)
    assert h._is_reprise_graduelle(intr) is True


def test_reprise_graduelle_read_from_interruption() -> None:
    # The flag is listed as an interruption-level field, so it must be honoured there too and not only at the payload root.
    intr = make_interruption(dateFin=None, repriseGraduellePossible=True)
    h = harness(etat="N", interruptions=[intr])
    assert h._is_reprise_graduelle(intr) is True


def test_reprise_graduelle_absent_is_false() -> None:
    intr = make_interruption(dateFin=None)
    h = harness(etat="N", interruptions=[intr])
    assert h._is_reprise_graduelle(intr) is False


# ---------------------------------------------------------------------------
# _interruption_attributes
# ---------------------------------------------------------------------------


def test_attributes_parse_date_fields_to_localized_iso() -> None:
    raw = hours_from_now(-2)
    intr = {"dateDebut": raw}
    h = harness()
    attrs = h._interruption_attributes(intr, ("dateDebut",))
    assert attrs["dateDebut"] == h._parse_dt(raw).isoformat()


def test_attributes_omit_none_values() -> None:
    intr = {"dateFin": None, "nbClient": 42}
    h = harness()
    attrs = h._interruption_attributes(intr, ("dateFin", "nbClient"))
    assert "dateFin" not in attrs
    assert attrs["nbClient"] == 42


def test_attributes_keep_falsy_non_none_values() -> None:
    intr = {"interruptionPlanifiee": False, "nbClient": 0}
    h = harness()
    attrs = h._interruption_attributes(intr, ("interruptionPlanifiee", "nbClient"))
    assert attrs["interruptionPlanifiee"] is False
    assert attrs["nbClient"] == 0


def test_attributes_unparseable_date_falls_back_to_raw() -> None:
    intr = {"dateDebut": "not-a-date"}
    h = harness()
    attrs = h._interruption_attributes(intr, ("dateDebut",))
    assert attrs["dateDebut"] == "not-a-date"
