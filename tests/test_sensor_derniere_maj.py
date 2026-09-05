"""Regression tests for the "Dernière MAJ" sensor.

The sensor used to fall back to ``coordinator.last_update_success_time``, an
attribute Home Assistant's DataUpdateCoordinator does not define. Guarded by a
``hasattr`` check, the fallback silently never fired, so the sensor reported
``unknown`` whenever the API carried no ``datePublication`` — that is, in
normal operation, outside an outage.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from custom_components.hydropannes.sensor import HydroPannesDerniereMAJSensor

from .conftest import FakeCoordinator, hours_from_now, make_interruption, make_payload


def maj_for(payload: dict[str, Any], last_success_time=None):
    """Return the sensor's native_value for a payload and coordinator clock.

    The sensor is built with ``__new__`` to bypass the Home Assistant entity
    constructor; ``native_value`` only reads the coordinator.
    """
    sensor = HydroPannesDerniereMAJSensor.__new__(HydroPannesDerniereMAJSensor)
    sensor.coordinator = FakeCoordinator(payload, last_success_time)  # type: ignore[assignment]
    return sensor.native_value


def test_falls_back_to_last_success_time_without_outage() -> None:
    """No interruption: the sensor reports the last successful poll."""
    now = dt_util.utcnow()
    payload = make_payload(etat="A", interruptions=[])
    assert maj_for(payload, now) == now


def test_date_publication_wins_over_last_success_time() -> None:
    """During an outage the API's own publication timestamp takes precedence."""
    published = hours_from_now(-1)
    intr = make_interruption(dateFin=None, datePublication=published)
    payload = make_payload(etat="N", interruptions=[intr])

    sensor = HydroPannesDerniereMAJSensor.__new__(HydroPannesDerniereMAJSensor)
    sensor.coordinator = FakeCoordinator(payload, dt_util.utcnow())  # type: ignore[assignment]
    assert sensor.native_value == sensor._parse_dt(published)


def test_none_before_first_successful_poll() -> None:
    """Nothing fetched yet: the sensor has no value to report."""
    assert maj_for(make_payload(etat="A", interruptions=[]), None) is None
