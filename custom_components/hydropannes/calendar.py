"""Calendar of the planned interruptions of a location."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util
from pyhydropannes.const import GRADUAL_RESTORATION_END_MARGIN, GRADUAL_RESTORATION_PLANNED_MINUTES

from .entity import HydroPannesEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from pyhydropannes import Interruption

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
    _write_after_details = True
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
            if not intr.planned or intr.is_cancelled:
                continue
            event = self._event(intr)
            if event:
                events.append(event)
        return sorted(events, key=lambda e: e.start)

    def _event(self, intr: Interruption) -> CalendarEvent | None:
        debut, fin = intr.effective_start, intr.effective_end
        if debut is None:
            return None
        debut = dt_util.as_local(debut)
        duree = intr.planned_duration_minutes
        if fin is None or fin <= debut:
            fin = debut + (
                timedelta(minutes=duree) if duree is not None and duree > 0 else _DEFAULT_LENGTH
            )
        fin = dt_util.as_local(fin)
        en = self._english
        lines = []
        if duree is not None and duree >= GRADUAL_RESTORATION_PLANNED_MINUTES:
            au_plus_tard = _format(fin + GRADUAL_RESTORATION_END_MARGIN)
            lines.append(
                f"Power may be restored gradually, until {au_plus_tard} at the latest."
                if en
                else f"Le service pourrait être rétabli graduellement, au plus tard à {au_plus_tard}."
            )
        # On an interruption not yet postponed, the report dates are the fallback slot the site lists under "En cas de report".
        if not intr.is_postponed and intr.postponed_start:
            report_debut = _format(intr.postponed_start)
            lines.append(
                f"In case of postponement: {report_debut}."
                if en
                else f"En cas de report : {report_debut}."
            )
        return CalendarEvent(
            start=debut,
            end=fin,
            summary="Planned service interruption" if en else "Interruption planifiée",
            description="\n".join(lines) or None,
            uid=intr.id,
        )


def _format(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%Y-%m-%d %H:%M")
