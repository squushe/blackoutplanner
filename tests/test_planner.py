from datetime import datetime, timedelta, timezone

import pytest

from blackout_planner.domain import Device, Task, build_plan
from blackout_planner.storage import Store, import_week

NOW = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)


def task(device, minutes=60, hours=4, **kwargs):
    return Task(device.id, device.name, minutes, (NOW + timedelta(hours=hours)).isoformat(), **kwargs)


def test_non_interruptible_cannot_cross_outage():
    device = Device("Прання")
    week = [[False] * 48 for _ in range(7)]
    week[0][16] = week[0][18] = True
    result = build_plan([device], [task(device)], week, NOW)
    assert not result.segments
    assert result.conflicts


def test_interruptible_is_split_between_windows():
    device = Device("Заряджання", kind="battery")
    week = [[False] * 48 for _ in range(7)]
    week[0][16] = week[0][18] = True
    result = build_plan([device], [task(device)], week, NOW)
    assert len(result.segments) == 2
    assert sum((s.end - s.start).total_seconds() for s in result.segments) == 3600


def test_parallel_power_limit_and_priority():
    first, second = Device("Бойлер", power=2000), Device("Плита", power=2000)
    a, b = task(first, priority=5), task(second, priority=1)
    result = build_plan([first, second], [b, a], [[True] * 48 for _ in range(7)], NOW)
    segments = {s.task_id: s for s in result.segments}
    assert segments[a.id].start == NOW
    assert segments[b.id].start == segments[a.id].end


def test_failed_task_does_not_reserve_partial_capacity():
    first, second = Device("Довга", power=3000), Device("Коротка", power=3000)
    a, b = task(first, 300, priority=5, interruptible=True), task(second, 60)
    result = build_plan([first, second], [a, b], [[True] * 48 for _ in range(7)], NOW)
    assert a.id in result.conflicts
    assert result.segments[0].start == NOW


def test_same_device_does_not_run_two_tasks_at_once():
    device = Device("Пральна машина", power=100)
    result = build_plan([device], [task(device), task(device)],
                        [[True] * 48 for _ in range(7)], NOW)
    assert result.segments[0].end <= result.segments[1].start


def test_charging_estimate():
    assert Device("Павербанк", kind="battery", power=20).charging_minutes(100) == 157


def test_unknown_schedule_never_assumes_power():
    device = Device("Пристрій")
    result = build_plan([device], [task(device)], [[None] * 48 for _ in range(7)], NOW)
    assert not result.segments


def test_rounding_never_exceeds_deadline():
    device = Device("Пристрій")
    now = NOW + timedelta(seconds=1)
    value = task(device, 60, hours=1)
    assert value.id in build_plan([device], [value], [[True] * 48 for _ in range(7)], now).conflicts


def test_storage_roundtrip(tmp_path):
    path = tmp_path / "planner.sqlite3"
    store = Store(path)
    device = Device("Ноутбук")
    value = task(device)
    store.save(device)
    store.save(value)
    store.set("week", [[True] * 48 for _ in range(7)])
    store.close()
    reopened = Store(path)
    assert reopened.devices() == [device]
    assert reopened.tasks() == [value]
    assert reopened.get("week")[0][0] is True
    reopened.close()


def test_import_rejects_overlap_and_missing_intervals(tmp_path):
    source = tmp_path / "week.csv"
    source.write_text("day,start,end,power\n0,00:00,24:00,1\n0,00:00,01:00,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="перетинаються"):
        import_week(str(source))
    source.write_text("day,start,end,power\n0,00:00,24:00,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Заповніть"):
        import_week(str(source))
