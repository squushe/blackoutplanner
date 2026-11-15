from datetime import UTC, datetime, timedelta

from blackout_planner.domain import Device, Plan, Task
from blackout_planner.notifications import Notice, build_notices, due_notices
from blackout_planner.platform_services import Autostart, desktop_exec


def test_linux_autostart_without_changing_user_settings(tmp_path):
    manager = Autostart(tmp_path, platform="linux", config_dir=tmp_path / "config")
    assert not manager.enabled()
    manager.set_enabled(True)
    assert manager.enabled()
    content = manager.desktop_path.read_text(encoding="utf-8")
    assert "--background" in content and "Terminal=false" in content
    manager.set_enabled(False)
    assert not manager.enabled()
    assert "%%" in desktop_exec(["/folder/100%/app"])


def test_outage_alerts_cross_midnight_and_deduplicate():
    now = datetime(2026, 11, 16, 23, 30, tzinfo=UTC)
    week = [[True] * 48 for _ in range(7)]
    week[1][0:2] = [False, False]
    device = Device("Павербанк", kind="battery", power=20)
    task = Task(device.id, "Зарядити", 157, (now + timedelta(hours=2)).isoformat(), target=100)
    events = build_notices(week, [], Plan(), [task], [device], now)
    due = due_notices(events, now, now - timedelta(seconds=30), {})
    assert len(due) == 1
    assert "00:00" in due[0].body and "заряд" in due[0].body
    assert not due_notices(events, now, now - timedelta(seconds=30), {due[0].key: True})


def test_sleep_skips_old_alerts_but_keeps_conflicts():
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    old = Notice("outage", now - timedelta(minutes=5), "", "")
    conflict = Notice("conflict", now - timedelta(days=1), "", "", "task")
    assert due_notices([old, conflict], now, now - timedelta(hours=1), {}) == [conflict]


def test_plan_change_cancels_removed_power_transition():
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    week = [[True] * 48 for _ in range(7)]
    week[0][25] = False
    before = build_notices(week, [], Plan(), [], [], now)
    assert any(event.at == now and event.kind == "outage" for event in before)
    overrides = [
        {"start": now.isoformat(), "end": (now + timedelta(hours=2)).isoformat(), "power": True}
    ]
    after = build_notices(week, overrides, Plan(), [], [], now)
    assert not any(event.at == now and event.kind == "outage" for event in after)
