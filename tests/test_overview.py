from datetime import UTC, datetime, timedelta

from blackout_planner.overview import next_power_change


def test_next_power_change_uses_actual_week_boundary():
    now = datetime(2026, 11, 16, 13, 20, tzinfo=UTC)
    week = [[True] * 48 for _ in range(7)]
    week[0][28:32] = [False] * 4
    moment, state = next_power_change(week, [], now)
    assert moment == now.replace(hour=14, minute=0)
    assert state is False


def test_manual_power_override_changes_next_transition():
    now = datetime(2026, 11, 16, 13, 20, tzinfo=UTC)
    week = [[True] * 48 for _ in range(7)]
    change = {
        "start": now.isoformat(),
        "end": (now + timedelta(minutes=45)).isoformat(),
        "power": False,
    }
    moment, state = next_power_change(week, [change], now)
    assert moment == now + timedelta(minutes=45)
    assert state is True


def test_constant_week_does_not_invent_next_outage():
    assert (
        next_power_change(
            [[True] * 48 for _ in range(7)], [], datetime(2026, 11, 16, 12, tzinfo=UTC)
        )
        is None
    )
