"""Calendar of the planned interruptions of a location."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .const import ETAT_PLANIFIE_REPORTE, GRAP_DUREE_PREVUE_MINUTES, GRAP_FIN_MARGE
from .entity import HydroPannesEntity
from .model import effective_dates, is_planned, is_planned_cancelled, parse_dt

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import HydroPannesConfigEntry

PARALLEL_UPDATES = 0

# Length given to an interruption whose end Hydro-Québec does not give, when dureePrevu is missing too.
_DEFAULT_LENGTH = timedelta(hours=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HydroPannesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the planned-interruptions calendar for a config entry."""
    async_add_entities([HydroPannesCalendar(entry.runtime_data, entry)])


class HydroPannesCalendar(HydroPannesEntity, CalendarEntity):
    """One event per planned interruption that is not cancelled, on its effective window."""

    _attr_translation_key = "interruptions_planifiees"
    _unique_id_suffix = "calendrier"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the planned interruption under way, or else the next one."""
        now = dt_util.now()
        upcoming = [e for e in self._events() if e.end > now]
        return min(upcoming, key=lambda e: e.start) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the events overlapping the requested range.

        Only what the last payload lists can be shown: Hydro-Québec drops an interruption from the payload some time after it ends, so past events disappear with it.
        """
        return [e for e in self._events() if e.end > start_date and e.start < end_date]

    def _events(self) -> list[CalendarEvent]:
        events = []
        for intr in self._etat.interruptions:
            if not is_planned(intr) or is_planned_cancelled(intr):
                continue
            event = self._event(intr)
            if event:
                events.append(event)
        return sorted(events, key=lambda e: e.start)

    def _event(self, intr: dict[str, Any]) -> CalendarEvent | None:
        debut, fin = effective_dates(intr)
        if debut is None:
            return None
        duree = intr.get("dureePrevu")
        if fin is None or fin <= debut:
            fin = debut + (
                timedelta(minutes=duree)
                if isinstance(duree, int | float) and duree > 0
                else _DEFAULT_LENGTH
            )
        en = self._english
        lines = []
        if isinstance(duree, int | float) and duree >= GRAP_DUREE_PREVUE_MINUTES:
            au_plus_tard = _format(fin + GRAP_FIN_MARGE)
            lines.append(
                f"Power may be restored gradually, until {au_plus_tard} at the latest."
                if en
                else f"Le service pourrait être rétabli graduellement, au plus tard à {au_plus_tard}."
            )
        # On an interruption not yet postponed, the report dates are the fallback slot the site lists under "En cas de report".
        if intr.get("etat") != ETAT_PLANIFIE_REPORTE:
            report_debut = parse_dt(intr.get("dateDebutReport"))
            if report_debut:
                lines.append(
                    f"In case of postponement: {_format(report_debut)}."
                    if en
                    else f"En cas de report : {_format(report_debut)}."
                )
        ident = intr.get("idInterruption") or {}
        uid = "-".join(
            str(ident.get(k, "")) for k in ("site", "typeObjet", "noInterruption", "noSection")
        )
        return CalendarEvent(
            start=debut,
            end=fin,
            summary="Planned service interruption" if en else "Interruption planifiée",
            description="\n".join(lines) or None,
            uid=uid if uid.strip("-") else None,
        )


def _format(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%Y-%m-%d %H:%M")
