"""Reading of a Hydro-Québec Info-pannes payload.

The coordinator builds one EtatLieu per successful poll, and every entity reads its fields instead of re-deriving the outage selection on each state write. The rules follow the Info-pannes site. Functions taking a single interruption do not depend on the root etat; the EtatLieu methods do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    ETAT_PANNE_TERMINEE,
    ETAT_PLANIFIE_ANNULE,
    ETAT_PLANIFIE_DECALE,
    ETAT_PLANIFIE_REPORTE,
    ETATS_PANNE_EN_COURS,
    NIVEAU_URGENCE_MAJEURS,
    RAISON_ANNULATION_CODES,
    RAISON_ANNULATION_DEFAUT,
)

# Suffix of the dateDebut*/dateFin* pair holding the new window of a postponed or shifted planned interruption.
_NEW_WINDOW_SUFFIX = {ETAT_PLANIFIE_REPORTE: "Report", ETAT_PLANIFIE_DECALE: "Decalage"}

_FAR_FUTURE = datetime.max.replace(tzinfo=dt_util.UTC)

# ==========================================================================
# Dates
# ==========================================================================


def parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO datetime string to a localized datetime, or return None."""
    if not value:
        return None
    try:
        parsed = dt_util.parse_datetime(value)
    except (ValueError, TypeError):
        return None
    return dt_util.as_local(parsed) if parsed else None


def is_past(value: datetime | None) -> bool:
    """Return True if the datetime is now or earlier."""
    return value is not None and value <= dt_util.now()


def is_future(value: datetime | None) -> bool:
    """Return True if the datetime is later than now."""
    return value is not None and value > dt_util.now()


def round_up_quarter(value: datetime) -> datetime:
    """Round a time up to the next quarter hour, as the Info-pannes site does before comparing it to now.

    Only the minutes are rounded, seconds are kept, like the site's dateArrondie pipe.
    """
    quarters = math.ceil(value.minute / 15)
    if quarters == 4:
        return value.replace(minute=0) + timedelta(hours=1)
    return value.replace(minute=quarters * 15)


# ==========================================================================
# A single interruption
# ==========================================================================


def is_planned(intr: dict[str, Any]) -> bool:
    """Return True if the interruption is a planned one."""
    return bool(intr.get("interruptionPlanifiee", False))


def is_planned_postponed(intr: dict[str, Any]) -> bool:
    """Return True if the planned interruption was postponed (etat "R")."""
    return intr.get("etat") == ETAT_PLANIFIE_REPORTE


def is_planned_cancelled(intr: dict[str, Any]) -> bool:
    """Return True if the planned interruption was cancelled (etat "A").

    The Info-pannes site shows etat "A" as cancelled whatever the codeRemarque, even when report dates are present.
    """
    return intr.get("etat") == ETAT_PLANIFIE_ANNULE


def is_panne_majeure(intr: dict[str, Any]) -> bool:
    """Return True when the interruption carries a major-outage urgency level."""
    return intr.get("niveauUrgence") in NIVEAU_URGENCE_MAJEURS


def raison_annulation(intr: dict[str, Any]) -> str | None:
    """Return the cancellation or postponement reason slug, or None without a codeRemarque."""
    code = intr.get("codeRemarque")
    if code in (None, ""):
        return None
    return RAISON_ANNULATION_CODES.get(str(code), RAISON_ANNULATION_DEFAUT)


def effective_dates(intr: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """Return the effective (start, end) of an interruption.

    A postponed planned interruption (etat "R") uses dateDebutReport/dateFinReport and a shifted one (etat "E") uses dateDebutDecalage/dateFinDecalage, as the Info-pannes site does: the API keeps the original dateDebut as the abandoned slot. Any other etat, or a missing new start, falls back to dateDebut/dateFin.
    """
    suffix = _NEW_WINDOW_SUFFIX.get(intr.get("etat", ""))
    if suffix:
        debut = parse_dt(intr.get(f"dateDebut{suffix}"))
        if debut:
            return debut, parse_dt(intr.get(f"dateFin{suffix}"))
    return parse_dt(intr.get("dateDebut")), parse_dt(intr.get("dateFin"))


def is_terminated(intr: dict[str, Any]) -> bool:
    """Return True if the interruption is terminated (power restored).

    A postponed or shifted planned interruption is terminated only once its new end is past, and never without one: its original dateFin is the abandoned slot. Any other interruption is terminated once dateFin is past.
    """
    suffix = _NEW_WINDOW_SUFFIX.get(intr.get("etat", ""))
    if suffix:
        return is_past(parse_dt(intr.get(f"dateFin{suffix}")))
    return is_past(parse_dt(intr.get("dateFin")))


def is_future_planned(intr: dict[str, Any]) -> bool:
    """Return True if the interruption is a planned one with a future effective start."""
    return is_planned(intr) and is_future(effective_dates(intr)[0])


def interruption_attributes(intr: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Build an attributes dict for the given raw interruption keys.

    Date fields (keys starting with ``date``) are parsed to a localized ISO string so every entity exposes timestamps in the same format, and values that cannot be parsed fall back to the raw string. Keys whose value is None are omitted.
    """
    attrs: dict[str, Any] = {}
    for key in keys:
        val = intr.get(key)
        if val is None:
            continue
        if key.startswith("date") and val:
            parsed = parse_dt(val)
            attrs[key] = parsed.isoformat() if parsed else val
        else:
            attrs[key] = val
    return attrs


def supersedes_terminated(planned: dict[str, Any] | None) -> bool:
    """Return True when a planned interruption outranks a past outage: present, not cancelled, not terminated."""
    return planned is not None and not is_planned_cancelled(planned) and not is_terminated(planned)


def _outage_end_for_sort(intr: dict[str, Any]) -> datetime:
    """Return the end used to rank simultaneous outages, far in the future when there is none."""
    return parse_dt(intr.get("dateFinEstimeeMax")) or parse_dt(intr.get("dateFin")) or _FAR_FUTURE


def _planned_sort_key(intr: dict[str, Any]) -> tuple[bool, datetime]:
    """Rank planned interruptions like the Info-pannes site: cancelled last, then by original dateDebut."""
    return is_planned_cancelled(intr), parse_dt(intr.get("dateDebut")) or _FAR_FUTURE


# ==========================================================================
# A whole payload
# ==========================================================================


@dataclass
class EtatLieu:
    """What one payload says about a location, computed once per poll.

    ``panne_active`` is the unplanned outage to display, ``panne_terminee`` the most recently terminated one, ``planifiee`` the most relevant planned interruption, ``planifiees_en_attente`` the planned ones neither cancelled nor terminated (nearest first) and ``courante`` the interruption the detail sensors describe. ``non_synchronise`` mirrors the site's flag of the same name.
    """

    data: dict[str, Any] | None
    root_etat: str | None = None
    interruptions: list[dict[str, Any]] = field(default_factory=list)
    panne_active: dict[str, Any] | None = None
    panne_terminee: dict[str, Any] | None = None
    planifiee: dict[str, Any] | None = None
    planifiees_en_attente: list[dict[str, Any]] = field(default_factory=list)
    non_synchronise: bool = False
    courante: dict[str, Any] | None = None

    @classmethod
    def depuis(cls, data: dict[str, Any] | None) -> EtatLieu:
        """Read a payload, or return an empty state before the first successful poll.

        The fields are filled in order: each selection may rely on the ones before it.
        """
        etat = cls(
            data=data,
            root_etat=data.get("etat") if data else None,
            interruptions=list(data.get("interruptions", [])) if data else [],
        )
        etat.panne_active = etat._select_active_outage()
        etat.panne_terminee = etat._select_terminated_outage()
        etat.planifiee = etat._select_planned()
        etat.planifiees_en_attente = etat._select_pending_planned()
        etat.non_synchronise = etat._compute_non_synchronise()
        etat.courante = None if etat.non_synchronise else etat._select_current()
        return etat

    # ----------------------------------------------------------------------
    # Rules that depend on the root etat
    # ----------------------------------------------------------------------

    def is_active(self, intr: dict[str, Any]) -> bool:
        """Return True if the interruption is under way.

        An unplanned interruption is active from its own etat, as on the site: C, I or N is under way, T is terminated. A planned one, or an unplanned one with another etat, is active when the root etat is "N" and its end (the new window's end once postponed or shifted) is absent or in the future.
        """
        if not is_planned(intr):
            # The site goes by the interruption's own etat: a C with root etat "A" is still shown as an outage under way.
            etat = intr.get("etat")
            if etat in ETATS_PANNE_EN_COURS:
                return True
            if etat == ETAT_PANNE_TERMINEE:
                return False

        if self.root_etat != "N":
            return False

        # A postponed or shifted planned interruption is active only inside its new window: its dateDebut/dateFin are the abandoned slot, and the root etat can be "N" because of another outage before the new window starts.
        suffix = _NEW_WINDOW_SUFFIX.get(intr.get("etat", ""))
        if suffix and is_planned(intr):
            debut = parse_dt(intr.get(f"dateDebut{suffix}"))
            fin = parse_dt(intr.get(f"dateFin{suffix}"))
            return is_past(debut) and (fin is None or is_future(fin))
        date_fin = parse_dt(intr.get("dateFin"))
        return date_fin is None or is_future(date_fin)

    def is_planned_in_progress(self, intr: dict[str, Any]) -> bool:
        """Return True for a planned interruption under way: root etat "N", neither cancelled nor terminated."""
        return (
            is_planned(intr)
            and self.root_etat == "N"
            and not is_planned_cancelled(intr)
            and not is_terminated(intr)
        )

    def is_reprise_graduelle(self, intr: dict[str, Any] | None = None) -> bool:
        """Return True when Hydro-Québec signals a gradual service restoration.

        ``repriseGraduellePossible`` is read from the payload root and from the interruption, so the flag is not missed if Hydro-Québec reports it per interruption.
        """
        if intr is not None and intr.get("repriseGraduellePossible"):
            return True
        return bool(self.data and self.data.get("repriseGraduellePossible"))

    # ----------------------------------------------------------------------
    # Selection, run once by depuis()
    # ----------------------------------------------------------------------

    def _select_active_outage(self) -> dict[str, Any] | None:
        """Return the active unplanned outage to display, or None.

        Like the Info-pannes site, the unplanned interruptions are ranked major first, then by latest end. The first active one is kept, and any interruption ranked after it that overlaps it moves its dateDebut back. The returned dict is then a copy carrying that earlier dateDebut.
        """
        unplanned = [i for i in self.interruptions if not is_planned(i)]
        # Sort ascending then reverse, like the site, so that ties also come out in reverse payload order.
        ranked = sorted(unplanned, key=lambda i: (is_panne_majeure(i), _outage_end_for_sort(i)))[
            ::-1
        ]
        chosen: dict[str, Any] | None = None
        for intr in ranked:
            if chosen is None:
                if self.is_active(intr):
                    chosen = intr
                continue
            chosen_debut = parse_dt(chosen.get("dateDebut"))
            debut = parse_dt(intr.get("dateDebut"))
            if (
                chosen_debut
                and debut
                and debut < chosen_debut
                and _outage_end_for_sort(intr) > chosen_debut
            ):
                chosen = {**chosen, "dateDebut": intr["dateDebut"]}
        return chosen

    def _select_terminated_outage(self) -> dict[str, Any] | None:
        """Return the most recently terminated unplanned outage, the one with the latest dateFin when Hydro-Québec splits a panne into sections."""
        candidates = [i for i in self.interruptions if not is_planned(i) and is_terminated(i)]
        if not candidates:
            return None
        return max(
            candidates, key=lambda i: parse_dt(i.get("dateFin")) or dt_util.utc_from_timestamp(0)
        )

    def _select_pending_planned(self) -> list[dict[str, Any]]:
        """Return the planned interruptions that are neither cancelled nor terminated, nearest first."""
        pending = (
            i
            for i in self.interruptions
            if is_planned(i) and not is_planned_cancelled(i) and not is_terminated(i)
        )
        return sorted(pending, key=_planned_sort_key)

    def _select_planned(self) -> dict[str, Any] | None:
        """Return the most relevant planned interruption, or None.

        Priority: the active one, then the nearest future one not cancelled, then the nearest future one, then the first listed. "Nearest" follows the Info-pannes ranking, by original dateDebut.
        """
        planned = [i for i in self.interruptions if is_planned(i)]
        if not planned:
            return None
        for p in planned:
            if self.is_active(p):
                return p
        ranked = sorted(planned, key=_planned_sort_key)
        for p in ranked:
            if is_future_planned(p) and not is_planned_cancelled(p):
                return p
        for p in ranked:
            if is_future_planned(p):
                return p
        return planned[0]

    def _compute_non_synchronise(self) -> bool:
        """Return True when the root etat and the listed interruptions disagree, as the site's nonSynchronise flag.

        Either the root etat is "A" while an unplanned interruption is under way, or it is "N" while no unplanned outage is under way and no planned interruption is in progress. The site then shows an outage under way without any detail ("Des précisions suivront dès que l'information sur la panne sera disponible").
        """
        if self.root_etat == "A":
            return self.panne_active is not None
        if self.root_etat != "N" or self.panne_active:
            return False
        return not (self.planifiee and self.is_planned_in_progress(self.planifiee))

    def _select_current(self) -> dict[str, Any] | None:
        """Return the interruption the detail sensors describe.

        Priority: the active unplanned outage, then the latest terminated one unless a planned interruption still pending outranks it, then the planned interruption, then the first listed.
        """
        if self.panne_active:
            return self.panne_active
        if self.panne_terminee and not supersedes_terminated(self.planifiee):
            return self.panne_terminee
        if self.planifiee:
            return self.planifiee
        return self.interruptions[0] if self.interruptions else None
