"""Tests de ``core/clock.py`` contra SPEC.md §9.1 e I2.

``FixedClock`` devuelve siempre el mismo instante; ``OffsetClock`` desplaza un
reloj base y ``advanced`` produce un reloj nuevo sin mutar el original.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.clock import Clock, FixedClock, OffsetClock

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.mark.spec
def test_fixed_clock_returns_same_moment_every_time():
    clock = FixedClock(T0)
    assert clock.now() == T0
    assert clock.now() == T0
    assert clock.now().tzinfo is not None


@pytest.mark.spec
def test_fixed_and_offset_clocks_satisfy_protocol():
    assert isinstance(FixedClock(T0), Clock)
    assert isinstance(OffsetClock(FixedClock(T0), timedelta(days=1)), Clock)


@pytest.mark.spec
def test_offset_clock_adds_offset_to_base():
    clock = OffsetClock(FixedClock(T0), timedelta(days=30))
    assert clock.now() == T0 + timedelta(days=30)


@pytest.mark.spec
def test_offset_clock_negative_offset_goes_back():
    clock = OffsetClock(FixedClock(T0), timedelta(days=-2))
    assert clock.now() == T0 - timedelta(days=2)


@pytest.mark.spec
def test_offset_clock_advanced_is_immutable_and_accumulates():
    base = OffsetClock(FixedClock(T0), timedelta(days=1))
    later = base.advanced(timedelta(days=2))
    assert later is not base
    assert base.now() == T0 + timedelta(days=1)
    assert later.now() == T0 + timedelta(days=3)
    assert later.base is base.base
    assert later.advanced(timedelta(hours=12)).now() == T0 + timedelta(days=3, hours=12)


@pytest.mark.spec
def test_offset_clock_can_wrap_another_offset_clock():
    inner = OffsetClock(FixedClock(T0), timedelta(days=1))
    outer = OffsetClock(inner, timedelta(days=1))
    assert outer.now() == T0 + timedelta(days=2)
