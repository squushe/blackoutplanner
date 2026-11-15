from datetime import UTC, datetime, timedelta

import pytest

from blackout_planner.calendar_export import export_ics
from blackout_planner.domain import Device, Plan, Segment, Task
from blackout_planner.storage import Store


def test_live_wal_backup_and_transactional_restore(tmp_path):
    store = Store(tmp_path / "live.sqlite3")
    device = Device("Пристрій")
    store.save(device)
    store.set("week", [[True] * 48 for _ in range(7)])
    copy = tmp_path / "backup.sqlite3"
    store.backup(copy)
    store.save(Device("Зайвий"))
    safety = store.restore(copy)
    assert store.devices() == [device]
    assert safety.is_file()
    original = Store(safety)
    assert len(original.devices()) == 2
    original.close()
    with pytest.raises(ValueError):
        store.backup(store.path)
    store.close()


def test_broken_backup_never_changes_current_data(tmp_path):
    store = Store(tmp_path / "live.sqlite3")
    store.save(Device("Важливі дані"))
    backup = Store(tmp_path / "invalid.sqlite3")
    backup.set("week", [None])
    backup.close()
    with pytest.raises(ValueError):
        store.restore(tmp_path / "invalid.sqlite3")
    assert len(store.devices()) == 1
    store.close()


def test_calendar_utf8_folding_escaping_and_stable_ids():
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    task = Task("device", "Зарядити; ноутбук,\n" + "Україна" * 30, 30, now.isoformat())
    plan = Plan([Segment(task.id, now, now + timedelta(minutes=30))])
    data = export_ics(plan, [task], now)
    assert all(len(line) <= 75 for line in data.split(b"\r\n"))
    unfolded = data.decode().replace("\r\n ", "")
    assert "DTSTART:20261116T120000Z" in unfolded
    assert "DTEND:20261116T123000Z" in unfolded
    assert "Зарядити\\; ноутбук\\,\\n" in unfolded
    assert f"UID:{task.id}-0@blackout-planner.local" in unfolded
    assert data.endswith(b"END:VCALENDAR\r\n")


@pytest.mark.parametrize("key,value", [
    ("overrides", [{"start": "2026-11-16T12:00:00+00:00", "end": "2026-11-16T11:00:00+00:00", "power": False}]),
    ("power_limit", -100),
    ("algorithm", "unknown"),
])
def test_invalid_backup_settings_are_rejected_before_restore(tmp_path, key, value):
    current = Store(tmp_path / "live.sqlite3")
    current.save(Device("Поточний пристрій"))
    backup = Store(tmp_path / "invalid.sqlite3")
    backup.set(key, value)
    backup.close()
    with pytest.raises(ValueError):
        current.restore(tmp_path / "invalid.sqlite3")
    assert current.devices()[0].name == "Поточний пристрій"
    current.close()
