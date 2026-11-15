"""Відтворюване порівняння базової евристики та локальної DP оптимізації.

Запуск: python -m experiments.compare --output experiments/results --repeats 3
"""

import argparse
import csv
import json
import platform
import random
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from blackout_planner.domain import BatteryProfile, Device, Task, build_plan

SEED = 20261115
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def scenarios():
    rng = random.Random(SEED)
    for size in (5, 10, 20, 40):
        for case in range(8):
            window = rng.choice((90, 120, 180, 240))
            devices = [Device(f"Прилад {i}", power=2000, id=f"device-{i}") for i in range(size)]
            tasks = [
                Task(
                    d.id,
                    d.name,
                    rng.choice((15, 30, 45, 60, 90)),
                    (NOW + timedelta(minutes=window)).isoformat(),
                    priority=rng.randint(1, 5),
                    id=f"task-{i:03}",
                )
                for i, d in enumerate(devices)
            ]
            week = [[False] * 48 for _ in range(7)]
            week[0][24 : 24 + window // 30] = [True] * (window // 30)
            yield f"sequential-{size}-{case}", "sequential", devices, tasks, week, None
    for case in range(16):
        devices = [
            Device(f"Прилад {i}", power=rng.choice((20, 65, 100, 1500, 2000)), id=f"device-{i}")
            for i in range(15)
        ]
        tasks = [
            Task(
                d.id,
                d.name,
                rng.choice((30, 60, 90, 120)),
                (NOW + timedelta(hours=rng.randint(2, 12))).isoformat(),
                priority=rng.randint(1, 5),
                interruptible=rng.choice((True, False)),
                id=f"task-{i:03}",
            )
            for i, d in enumerate(devices)
        ]
        week = [[(slot // 4) % 2 == 0 for slot in range(48)] for _ in range(7)]
        battery = BatteryProfile(
            compatible_ids=[d.id for d in devices if d.power <= 100], enabled=True
        )
        yield f"household-{case}", "household", devices, tasks, week, battery


def validate(plan, devices, tasks, week, battery):
    """Незалежна перевірка сегментів, дедлайнів і хвилинних ресурсів."""
    by_task = {t.id: t for t in tasks}
    by_device = {d.id: d for d in devices}
    timeline = {}
    assigned = {}
    reserve_wh = 0
    for segment in plan.segments:
        task = by_task[segment.task_id]
        device = by_device[task.device_id]
        assert segment.start >= NOW and segment.end <= datetime.fromisoformat(task.deadline)
        assigned[task.id] = assigned.get(task.id, 0) + int(
            (segment.end - segment.start).total_seconds() / 60
        )
        minute = segment.start
        while minute < segment.end:
            grid, reserve, occupied = timeline.setdefault(minute, [0, 0, set()])
            assert device.id not in occupied
            occupied.add(device.id)
            if week[minute.weekday()][minute.hour * 2 + minute.minute // 30]:
                grid += device.power
            else:
                assert battery and device.id in battery.compatible_ids
                reserve += device.power
                reserve_wh += device.power / (60 * battery.efficiency)
            assert grid <= 3500
            assert reserve <= (battery.output_w if battery else 0)
            timeline[minute] = [grid, reserve, occupied]
            minute += timedelta(minutes=1)
    for task_id, minutes in assigned.items():
        assert minutes == by_task[task_id].remaining
        if not by_task[task_id].interruptible:
            assert sum(s.task_id == task_id for s in plan.segments) == 1
    assert reserve_wh <= (battery.usable_wh if battery else 0) + 1e-6


def run(output, repeats=3):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, category, devices, tasks, week, battery in scenarios():
        for algorithm in ("greedy", "dp"):
            timings = []
            for _ in range(repeats):
                start = time.perf_counter()
                plan = build_plan(devices, tasks, week, NOW, battery=battery, algorithm=algorithm)
                timings.append((time.perf_counter() - start) * 1000)
            validate(plan, devices, tasks, week, battery)
            completed = {segment.task_id for segment in plan.segments}
            rows.append(
                dict(
                    case=name,
                    category=category,
                    algorithm=algorithm,
                    tasks=len(tasks),
                    completed=len(completed),
                    weight=sum(t.priority for t in tasks if t.id in completed),
                    conflicts=len(plan.conflicts),
                    late=0,
                    reserve_wh=round(plan.reserve_used_wh, 4),
                    median_ms=round(statistics.median(timings), 4),
                )
            )
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "seed": SEED,
        "repeats": repeats,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cases": len(rows) // 2,
        "categories": {},
    }
    lines = [
        "# Порівняння алгоритмів Blackout Planner",
        "",
        f"Seed: {SEED}. Сценаріїв: {len(rows) // 2}. Повторів вимірювання: {repeats}.",
        "",
        f"Середовище: Python {summary['python']}, {summary['platform']}.",
        "",
        "| Набір | Алгоритм | Виконано задач сумарно | Сума пріоритетів | Медіана часу, мс |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for category in ("sequential", "household"):
        summary["categories"][category] = {}
        for algorithm in ("greedy", "dp"):
            values = [r for r in rows if r["category"] == category and r["algorithm"] == algorithm]
            stats = dict(
                completed=sum(r["completed"] for r in values),
                weight=sum(r["weight"] for r in values),
                median_ms=round(statistics.median(r["median_ms"] for r in values), 4),
            )
            summary["categories"][category][algorithm] = stats
            lines.append(
                f"| {category} | {algorithm} | {stats['completed']} | {stats['weight']} | {stats['median_ms']:.3f} |"
            )
    lines += [
        "",
        "Усі отримані плани пройшли незалежну перевірку тривалості, дедлайнів, "
        "зайнятості пристроїв, потужності та енергетичного залишку.",
        "",
        "Sequential: одне вікно, усі дедлайни на його кінці, попарно несумісні за "
        "потужністю навантаження. DP максимізує суму пріоритетів у цій підзадачі.",
        "",
        "Household: різні дедлайни, переривання, паралельні навантаження та резерв. "
        "Локальна DP тут не застосовується, тому обидва режими використовують базову "
        "евристику. Це перевірка меж застосування, а не доказ покращення загальної задачі.",
        "",
        "Дедлайни є жорстким обмеженням: прострочені задачі не призначаються, тому "
        "запізнення допустимих планів дорівнює нулю. Незадоволені задачі враховані як конфлікти. "
        "Час залежить від комп’ютера та фонового навантаження.",
        "",
        "Відтворення: `python -m experiments.compare --output experiments/results --repeats 3`.",
    ]
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("experiments/results"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats має бути додатним")
    run(args.output, args.repeats)
