"""Shared fixtures and helpers for the Hydro-Pannes test suite.

The business logic under test lives in ``HydroPannesHelperMixin`` and only
depends on a ``coordinator`` attribute that exposes ``.data``. Rather than
spinning up a full Home Assistant instance, these tests drive the mixin (and
the sensor classes that inherit from it) through a lightweight fake
coordinator, which keeps them fast and focused on state-transition logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util
import pytest


class FakeCoordinator:
    """Minimal stand-in for HydroPannesDataUpdateCoordinator.

    Only exposes the ``data`` attribute the helper mixin reads.
    """

    def __init__(
        self,
        data: dict[str, Any] | None,
        last_success_time: datetime | None = None,
    ) -> None:
        """Store the API payload the mixin will interpret."""
        self.data = data
        self.last_success_time = last_success_time


def iso(dt: datetime) -> str:
    """Render a datetime as an ISO string, matching the HQ API format."""
    return dt.isoformat()


def hours_from_now(hours: float) -> str:
    """Return an ISO datetime string offset from now by ``hours``."""
    return iso(dt_util.now() + timedelta(hours=hours))


def make_interruption(**overrides: Any) -> dict[str, Any]:
    """Build an interruption dict with sensible defaults.

    Pass field overrides as keyword arguments; ``None`` values are dropped so
    tests can express "field absent" by passing ``field=None``.
    """
    interruption: dict[str, Any] = {
        "dateDebut": hours_from_now(-2),
        "etat": "N",
        "interruptionPlanifiee": False,
    }
    interruption.update(overrides)
    return {k: v for k, v in interruption.items() if v is not None}


def make_payload(
    etat: str = "N", interruptions: list[dict[str, Any]] | None = None, **root: Any
) -> dict[str, Any]:
    """Build a top-level API payload with the given root etat and interruptions."""
    payload: dict[str, Any] = {
        "etat": etat,
        "idLieuConso": "0000001234",
        "interruptions": interruptions if interruptions is not None else [],
    }
    payload.update(root)
    return payload


@pytest.fixture
def make_coordinator():
    """Return a factory that wraps a payload in a FakeCoordinator."""

    def _factory(data: dict[str, Any] | None) -> FakeCoordinator:
        return FakeCoordinator(data)

    return _factory
