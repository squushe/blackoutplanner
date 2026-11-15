"""Побудова подій і відбір актуальних нагадувань без залежності від ОС."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .domain import power_at


@dataclass(frozen=True)
class Notice:
    kind: str
    at: datetime
    title: str
    body: str
    object_id: str = ""

    @property
    def key(self):
        # Відсоток заряду в тексті не змінює ідентичність попередження.
        value = [self.kind, self.object_id, self.at.astimezone(UTC).isoformat()]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def upcoming_text(plan, tasks, now):
    names = {task.id: task.name for task in tasks}
    upcoming = sorted(
        (s for s in plan.segments if now <= s.start < now + timedelta(hours=3)),
        key=lambda s: s.start,
    )
    seen = list(dict.fromkeys(names.get(s.task_id, "Задача") for s in upcoming))
    return ", ".join(seen[:4]) or "запланованих задач немає"


def build_notices(week, overrides, plan, tasks, devices, now):
    by_device = {d.id: d for d in devices}
    incomplete = []
    for task in tasks:
        if task.status in {"done", "cancelled"}:
            continue
        completed = task.completed
        if task.started_at:
            completed += max(
                0, int((now - datetime.fromisoformat(task.started_at)).total_seconds() // 60)
            )
        if completed >= task.minutes:
            continue
        suffix = ""
        device = by_device.get(task.device_id)
        if device and task.target is not None:
            remaining = max(0, task.minutes - completed)
            charge = max(
                0,
                min(
                    task.target,
                    task.target
                    - remaining * device.power * device.efficiency / 60 / device.capacity * 100,
                ),
            )
            suffix = f" (розрахунковий заряд {charge:.0f} %)"
        incomplete.append(task.name + suffix)
    notices = []
    origin = now.astimezone(UTC).replace(second=0, microsecond=0) - timedelta(minutes=35)
    previous = power_at(week, (origin - timedelta(minutes=1)).astimezone(now.tzinfo), overrides)
    for minute in range(3 * 1440 + 35):
        boundary = (origin + timedelta(minutes=minute)).astimezone(now.tzinfo)
        current = power_at(week, boundary, overrides)
        if previous is True and current is False:
            for lead in (30, 10):
                notices.append(
                    Notice(
                        "outage",
                        boundary - timedelta(minutes=lead),
                        "Наближається відключення",
                        f"За графіком світло зникне о {boundary:%H:%M}. За {lead} хв. "
                        + (
                            "Не завершено: " + "; ".join(incomplete[:3])
                            if incomplete
                            else "Усі задачі виконано."
                        ),
                        f"{boundary.isoformat()}:{lead}",
                    )
                )
        elif previous is False and current is True:
            confirmed = any(
                change["power"] and datetime.fromisoformat(change["start"]) == boundary
                for change in overrides
            )
            notices.append(
                Notice(
                    "power_on",
                    boundary,
                    "Світло з’явилося" if confirmed else "Почалося вікно живлення",
                    ("За вашим підтвердженням. " if confirmed else "За графіком. ")
                    + "План на 3 години: "
                    + upcoming_text(plan, tasks, boundary),
                )
            )
        previous = current
    if plan.conflicts:
        names = {task.id: task.name for task in tasks}
        identity = hashlib.sha256(
            json.dumps(sorted(plan.conflicts.items()), ensure_ascii=False).encode()
        ).hexdigest()
        first = next(iter(plan.conflicts))
        notices.append(
            Notice(
                "conflict",
                datetime(2000, 1, 1, tzinfo=UTC),
                "Задачі не вміщуються в розклад",
                "; ".join(
                    f"{names.get(key, 'Задача')}: {reason}"
                    for key, reason in list(plan.conflicts.items())[:3]
                )
                + ". Відкрийте повідомлення, щоб перенести задачу або переглянути план.",
                first + ":" + identity,
            )
        )
    for task in tasks:
        if task.status == "running" and task.started_at:
            finish = datetime.fromisoformat(task.started_at) + timedelta(minutes=task.remaining)
            notices.append(
                Notice(
                    "finish",
                    finish,
                    "Підтвердіть результат задачі",
                    f"Розрахунковий час завершився: {task.name}. Позначте виконання або уточніть прогрес.",
                    task.id,
                )
            )
    return notices


def due_notices(notices, now, last_check, history):
    selected = [
        event
        for event in notices
        if event.key not in history
        and event.at <= now
        and (event.kind == "conflict" or last_check < event.at)
    ]
    # Після сну застарілі попередження не відтворюються.
    if now - last_check > timedelta(minutes=2):
        selected = [event for event in selected if event.kind == "conflict"]
    return sorted(selected, key=lambda e: (e.kind == "conflict", e.at))
