"""Моделі й розрахунок розкладу без залежності від Qt та бази даних."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil, isfinite
from uuid import uuid4


def identifier() -> str:
    return uuid4().hex


@dataclass
class Device:
    name: str
    kind: str = "job"
    power: float = 100
    duration: int = 60
    interruptible: bool = False
    capacity: float = 74
    charge: float = 40
    efficiency: float = 0.85
    priority: int = 3
    id: str = field(default_factory=identifier)

    def validate(self):
        if not self.name.strip():
            raise ValueError("Введіть назву пристрою")
        if self.kind not in {"job", "battery"}:
            raise ValueError("Невідомий тип пристрою")
        if not isfinite(self.power) or not 0 < self.power <= 100000 or self.duration <= 0:
            raise ValueError("Потужність і тривалість мають бути додатними")
        if not 0 <= self.charge <= 100 or not 0 < self.capacity <= 1000000:
            raise ValueError("Перевірте ємність і рівень заряду")
        if not 0 < self.efficiency <= 1 or not 1 <= self.priority <= 5:
            raise ValueError("Перевірте ефективність і пріоритет")

    def charging_minutes(self, target: float) -> int:
        if not 0 <= target <= 100:
            raise ValueError("Цільовий заряд має бути від 0 до 100 %")
        return ceil(
            60 * self.capacity * max(0, target - self.charge) / 100 / (self.power * self.efficiency)
        )


@dataclass
class Task:
    device_id: str
    name: str
    minutes: int
    deadline: str
    priority: int = 3
    interruptible: bool = False
    completed: int = 0
    status: str = "pending"
    started_at: str | None = None
    target: float | None = None
    id: str = field(default_factory=identifier)

    @property
    def remaining(self):
        return max(0, self.minutes - self.completed)

    def validate(self):
        if not self.name.strip() or not self.device_id:
            raise ValueError("Введіть назву задачі та оберіть пристрій")
        if self.minutes <= 0 or not 0 <= self.completed <= self.minutes:
            raise ValueError("Перевірте тривалість і прогрес задачі")
        if not 1 <= self.priority <= 5:
            raise ValueError("Пріоритет має бути від 1 до 5")
        if datetime.fromisoformat(self.deadline).tzinfo is None:
            raise ValueError("Дедлайн має містити часовий пояс")


@dataclass(frozen=True)
class Segment:
    task_id: str
    start: datetime
    end: datetime


@dataclass
class Plan:
    segments: list[Segment] = field(default_factory=list)
    conflicts: dict[str, str] = field(default_factory=dict)


def blank_week():
    """None означає, що користувач ще не підтвердив стан клітинки."""
    return [[None for _ in range(48)] for _ in range(7)]


def validate_week(week):
    if len(week) != 7 or any(len(day) != 48 for day in week):
        raise ValueError("Потрібно 7 днів по 48 півгодинних інтервалів")
    if any(type(value) is not bool for day in week for value in day):
        raise ValueError("Заповніть усі інтервали графіка")


def minute_grid(now: datetime):
    value = now.replace(second=0, microsecond=0)
    return value + timedelta(minutes=1) if value < now else value


def build_plan(
    devices: list[Device],
    tasks: list[Task],
    week: list,
    now: datetime,
    power_limit: float = 3500,
    background_power: float = 0,
    horizon_days: int = 7,
) -> Plan:
    """Детермінована priority/EDF евристика з атомарним призначенням задачі.

    Хвилини зберігаються в UTC, клітинки тижня обираються в локальному поясі.
    Невідомий стан графіка не вважається доступним живленням.
    """
    if now.tzinfo is None:
        raise ValueError("Поточний час має містити часовий пояс")
    if power_limit <= 0 or not 0 <= background_power <= power_limit:
        raise ValueError("Перевірте ліміт потужності та фонове навантаження")
    if len(week) != 7 or any(len(day) != 48 for day in week):
        raise ValueError("Неправильна структура тижневого графіка")
    for device in devices:
        device.validate()
    for task in tasks:
        task.validate()

    start = minute_grid(now.astimezone(UTC))
    count = horizon_days * 1440
    ticks = [start + timedelta(minutes=k) for k in range(count)]
    available = []
    for tick in ticks:
        local = tick.astimezone(now.tzinfo)
        available.append(week[local.weekday()][local.hour * 2 + local.minute // 30] is True)
    load = [background_power] * count
    occupied: dict[str, set[int]] = {device.id: set() for device in devices}
    by_id = {device.id: device for device in devices}
    result = Plan()
    ordered = sorted(
        tasks,
        key=lambda task: (
            task.status != "running",
            -task.priority,
            datetime.fromisoformat(task.deadline),
            task.id,
        ),
    )
    for task in ordered:
        if task.status in {"done", "cancelled"} or not task.remaining:
            continue
        device = by_id.get(task.device_id)
        if not device:
            result.conflicts[task.id] = "Пристрій не знайдено"
            continue
        deadline = datetime.fromisoformat(task.deadline)
        if deadline.tzinfo is None:
            raise ValueError("Дедлайн має містити часовий пояс")
        end = min(count, int((deadline - start).total_seconds() // 60))
        if end <= 0:
            result.conflicts[task.id] = "Дедлайн уже минув"
            continue
        if device.power + background_power > power_limit:
            result.conflicts[task.id] = "Потужність пристрою перевищує доступний ліміт"
            continue
        feasible = [
            available[k] and load[k] + device.power <= power_limit and k not in occupied[device.id]
            for k in range(end)
        ]
        selected: list[int] = []
        if task.status == "running":
            # Розпочату роботу не можна непомітно відсунути на інший час.
            if end >= task.remaining and all(feasible[: task.remaining]):
                selected = list(range(task.remaining))
        elif task.interruptible or device.kind == "battery":
            selected = [k for k, ok in enumerate(feasible) if ok][: task.remaining]
        else:
            run = 0
            for k, ok in enumerate(feasible):
                run = run + 1 if ok else 0
                if run == task.remaining:
                    selected = list(range(k - run + 1, k + 1))
                    break
        if len(selected) != task.remaining:
            result.conflicts[task.id] = (
                "Поточне виконання конфліктує з графіком або лімітом; підтвердьте паузу"
                if task.status == "running"
                else "Недостатньо доступного часу до дедлайну"
                if task.interruptible or device.kind == "battery"
                else "Немає суцільного вікна з достатньою потужністю до дедлайну"
            )
            continue
        for k in selected:
            load[k] += device.power
            occupied[device.id].add(k)
        first = previous = selected[0]
        for k in selected[1:]:
            if k != previous + 1:
                result.segments.append(
                    Segment(task.id, ticks[first], ticks[previous] + timedelta(minutes=1))
                )
                first = k
            previous = k
        result.segments.append(
            Segment(task.id, ticks[first], ticks[previous] + timedelta(minutes=1))
        )
    return result
