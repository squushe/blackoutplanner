from datetime import UTC, datetime, timedelta

import pytest

from blackout_planner.domain import BatteryProfile, Device, Task, build_plan, knapsack, power_at

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
ON = [[True] * 48 for _ in range(7)]
OFF = [[False] * 48 for _ in range(7)]


def work(device, minutes=60, **values):
    return Task(device.id, device.name, minutes, (NOW + timedelta(hours=4)).isoformat(), **values)


def test_lock_preserves_exact_segments():
    device = Device("Ноутбук")
    task = work(device, locked_segments=[[(NOW + timedelta(hours=1)).isoformat(),
                                         (NOW + timedelta(hours=2)).isoformat()]])
    plan = build_plan([device], [task], ON, NOW)
    assert plan.segments[0].start == NOW + timedelta(hours=1)


def test_lock_cannot_cross_outage_or_deadline():
    device = Device("Прання")
    task = work(device, locked_segments=[[NOW.isoformat(),
                                         (NOW + timedelta(hours=1)).isoformat()]])
    override = [{"start": NOW.isoformat(), "end": (NOW + timedelta(hours=2)).isoformat(),
                 "power": False}]
    assert task.id in build_plan([device], [task], ON, NOW, overrides=override).conflicts
    assert power_at(ON, NOW + timedelta(hours=3), override) is True


def test_backup_energy_and_compatibility():
    device = Device("Роутер", power=100)
    task = work(device)
    battery = BatteryProfile(capacity_wh=100, charge=100, reserve=0, efficiency=1,
                             compatible_ids=[device.id], enabled=True)
    plan = build_plan([device], [task], OFF, NOW, battery=battery)
    assert not plan.conflicts
    assert plan.reserve_used_wh == pytest.approx(100)
    battery.charge = 99
    assert task.id in build_plan([device], [task], OFF, NOW, battery=battery).conflicts
    battery.charge = 100
    battery.compatible_ids = []
    assert task.id in build_plan([device], [task], OFF, NOW, battery=battery).conflicts


def test_reserve_power_shared_and_failed_job_rolls_back():
    a, b = Device("A", power=100), Device("B", power=100)
    battery = BatteryProfile(capacity_wh=200, charge=100, reserve=0, output_w=100,
                             efficiency=1, compatible_ids=[a.id, b.id], enabled=True)
    impossible, short = work(a, 300, priority=5, interruptible=True), work(b, 60)
    plan = build_plan([a, b], [impossible, short], OFF, NOW, battery=battery)
    assert impossible.id in plan.conflicts
    assert plan.segments[0].start == NOW
    assert plan.reserve_used_wh == pytest.approx(100)


def test_no_implicit_uninterrupted_transfer_between_sources():
    device = Device("Прилад", power=100)
    task = work(device, 60)
    task.deadline = (NOW + timedelta(hours=1)).isoformat()
    week = [[False] * 48 for _ in range(7)]
    week[0][24] = True
    battery = BatteryProfile(compatible_ids=[device.id], enabled=True)
    assert task.id in build_plan([device], [task], week, NOW, battery=battery).conflicts
    battery.continuous_transfer = True
    assert not build_plan([device], [task], week, NOW, battery=battery).conflicts


def test_autonomy_zero_load_and_power_limit():
    battery = BatteryProfile(capacity_wh=1000, charge=80, reserve=20, efficiency=.9)
    assert battery.autonomy_hours(100) == pytest.approx(5.4)
    assert battery.autonomy_hours(0) is None
    assert battery.autonomy_hours(1000) == 0


def test_dp_selects_best_weight_for_single_window():
    devices = [Device(name, power=2000) for name in ["A", "B", "C"]]
    tasks = [work(devices[0], 60, priority=5), work(devices[1], 30, priority=3),
             work(devices[2], 30, priority=3)]
    for task in tasks:
        task.deadline = (NOW + timedelta(hours=1)).isoformat()
    week = [[False] * 48 for _ in range(7)]
    week[0][24:26] = [True, True]
    greedy = build_plan(devices, tasks, week, NOW)
    dynamic = build_plan(devices, tasks, week, NOW, algorithm="dp")
    assert len({s.task_id for s in greedy.segments}) == 1
    assert len({s.task_id for s in dynamic.segments}) == 2
    assert sum(t.priority for t in knapsack(tasks, 60)) == 6
