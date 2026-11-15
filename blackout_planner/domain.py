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
    locked_segments: list[list[str]] = field(default_factory=list)

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
        for begin, end in self.locked_segments:
            begin, end = datetime.fromisoformat(begin), datetime.fromisoformat(end)
            if begin.tzinfo is None or end.tzinfo is None or begin >= end:
                raise ValueError("Некоректне ручне закріплення")


@dataclass(frozen=True)
class Segment:
    task_id: str
    start: datetime
    end: datetime


@dataclass
class Plan:
    segments: list[Segment] = field(default_factory=list)
    conflicts: dict[str, str] = field(default_factory=dict)
    reserve_used_wh: float = 0


@dataclass
class BatteryProfile:
    capacity_wh: float = 1000
    charge: float = 80
    reserve: float = 20
    output_w: float = 500
    efficiency: float = 0.9
    compatible_ids: list[str] = field(default_factory=list)
    continuous_transfer: bool = False
    enabled: bool = False

    def validate(self):
        if not (
            0 < self.capacity_wh <= 1000000
            and 0 <= self.reserve <= 100
            and 0 <= self.charge <= 100
            and 0 < self.output_w <= 100000
            and 0 < self.efficiency <= 1
        ):
            raise ValueError("Перевірте ємність, заряд, резерв і потужність акумулятора")

    @property
    def usable_wh(self):
        return self.capacity_wh * max(0, self.charge - self.reserve) / 100

    def autonomy_hours(self, power):
        self.validate()
        if power < 0:
            raise ValueError("Навантаження не може бути від’ємним")
        if power > self.output_w:
            return 0
        return self.usable_wh * self.efficiency / power if power else None


def power_at(week, moment, overrides=()):
    """Останнє датоване уточнення має перевагу над тижневим шаблоном."""
    for change in reversed(overrides):
        if (
            datetime.fromisoformat(change["start"])
            <= moment
            < datetime.fromisoformat(change["end"])
        ):
            return change["power"]
    return week[moment.weekday()][moment.hour * 2 + moment.minute // 30]


def validate_overrides(overrides):
    if not isinstance(overrides, list):
        raise ValueError("Уточнення графіка мають бути списком")
    for change in overrides:
        begin, end = datetime.fromisoformat(change["start"]), datetime.fromisoformat(change["end"])
        if (
            begin.tzinfo is None
            or end.tzinfo is None
            or begin >= end
            or type(change["power"]) is not bool
        ):
            raise ValueError("Некоректний інтервал уточнення живлення")


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
    overrides: list | None = None,
    battery: BatteryProfile | None = None,
    algorithm: str = "greedy",
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
    battery = battery or BatteryProfile()
    battery.validate()
    overrides = overrides or []
    validate_overrides(overrides)

    start = minute_grid(now.astimezone(UTC))
    count = horizon_days * 1440
    ticks = [start + timedelta(minutes=k) for k in range(count)]
    available = []
    for tick in ticks:
        local = tick.astimezone(now.tzinfo)
        available.append(power_at(week, local, overrides) is True)
    load = [background_power] * count
    reserve_load = [0.0] * count
    occupied: dict[str, set[int]] = {device.id: set() for device in devices}
    by_id = {device.id: device for device in devices}
    result = Plan()
    ordered = sorted(
        tasks,
        key=lambda task: (
            task.status != "running",
            not bool(task.locked_segments),
            -task.priority,
            datetime.fromisoformat(task.deadline),
            task.id,
        ),
    )
    if algorithm == "dp":
        ordered = optimize_window_order(
            ordered, by_id, available, start, power_limit, background_power, battery.enabled
        )
    elif algorithm != "greedy":
        raise ValueError("Невідомий алгоритм планування")
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
        if device.power + background_power > power_limit and not battery.enabled:
            result.conflicts[task.id] = "Потужність пристрою перевищує доступний ліміт"
            continue
        feasible = [
            (
                load[k] + device.power <= power_limit
                if available[k]
                else battery.enabled
                and device.id in battery.compatible_ids
                and reserve_load[k] + device.power <= battery.output_w
            )
            and k not in occupied[device.id]
            for k in range(end)
        ]

        def acceptable(indices):
            if len(indices) != task.remaining or not all(feasible[k] for k in indices):
                return False
            energy = sum(
                device.power / (60 * battery.efficiency) for k in indices if not available[k]
            )
            if result.reserve_used_wh + energy > battery.usable_wh + 1e-8:
                return False
            if not (task.interruptible or device.kind == "battery"):
                if any(b != a + 1 for a, b in zip(indices, indices[1:])):
                    return False
                if not battery.continuous_transfer and any(
                    available[a] != available[b] for a, b in zip(indices, indices[1:])
                ):
                    return False
            return True

        selected: list[int] = []
        if task.locked_segments and task.status != "running":
            for begin, finish in task.locked_segments:
                first = (datetime.fromisoformat(begin) - start).total_seconds() / 60
                last = (datetime.fromisoformat(finish) - start).total_seconds() / 60
                if first < 0 or last > end or not first.is_integer() or not last.is_integer():
                    selected = []
                    break
                selected.extend(range(int(first), int(last)))
            if selected != sorted(set(selected)) or not acceptable(selected):
                selected = []
        elif task.status == "running":
            # Розпочату роботу не можна непомітно відсунути на інший час.
            candidate = list(range(min(end, task.remaining)))
            if acceptable(candidate):
                selected = candidate
        elif task.interruptible or device.kind == "battery":
            energy = result.reserve_used_wh
            for k, ok in enumerate(feasible):
                cost = 0 if available[k] else device.power / (60 * battery.efficiency)
                if ok and energy + cost <= battery.usable_wh + 1e-8:
                    selected.append(k)
                    energy += cost
                    if len(selected) == task.remaining:
                        break
        else:
            run = 0
            for k, ok in enumerate(feasible):
                if k and not battery.continuous_transfer and available[k] != available[k - 1]:
                    run = 0
                run = run + 1 if ok else 0
                if run >= task.remaining:
                    candidate = list(range(k - task.remaining + 1, k + 1))
                    if acceptable(candidate):
                        selected = candidate
                        break
        if len(selected) != task.remaining:
            result.conflicts[task.id] = (
                "Ручне закріплення порушує графік, дедлайн або ресурсні обмеження"
                if task.locked_segments and task.status != "running"
                else "Поточне виконання конфліктує з графіком або лімітом; підтвердьте паузу"
                if task.status == "running"
                else "Недостатньо часу, потужності або енергії резерву до дедлайну"
                if task.interruptible or device.kind == "battery"
                else "Немає суцільного вікна з достатньою потужністю до дедлайну"
            )
            continue
        for k in selected:
            if available[k]:
                load[k] += device.power
            else:
                reserve_load[k] += device.power
                result.reserve_used_wh += device.power / (60 * battery.efficiency)
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


def knapsack(tasks, capacity):
    """0/1 DP: максимальна сума пріоритетів за послідовного виконання."""
    rows = [[0] * (capacity + 1)]
    for task in tasks:
        previous = rows[-1]
        current = previous.copy()
        for minute in range(task.remaining, capacity + 1):
            current[minute] = max(
                previous[minute], previous[minute - task.remaining] + task.priority
            )
        rows.append(current)
    chosen = []
    minute = capacity
    for index in range(len(tasks), 0, -1):
        if rows[index][minute] != rows[index - 1][minute]:
            chosen.append(tasks[index - 1])
            minute -= tasks[index - 1].remaining
    return list(reversed(chosen))


def optimize_window_order(tasks, devices, available, start, limit, background, has_battery):
    """Локальна DP для першого вікна з гарантовано послідовними навантаженнями.

    Загальна задача з паралельними приладами/резервом лишається евристичною.
    Кандидати попарно не можуть працювати одночасно за заданого ліміту.
    """
    if has_battery or any(t.status == "running" or t.locked_segments for t in tasks):
        return tasks
    first = next((k for k, value in enumerate(available) if value), None)
    if first is None:
        return tasks
    end = first
    while end < len(available) and available[end]:
        end += 1
    window_end = start + timedelta(minutes=end)
    candidates = [
        t
        for t in tasks
        if t.status not in {"done", "cancelled"}
        and t.remaining
        and not t.interruptible
        and t.device_id in devices
        and devices[t.device_id].kind == "job"
        and devices[t.device_id].power + background <= limit
        and datetime.fromisoformat(t.deadline) >= window_end
    ]
    if any(
        a.device_id != b.device_id
        and devices[a.device_id].power + devices[b.device_id].power + background <= limit
        for index, a in enumerate(candidates)
        for b in candidates[index + 1 :]
    ):
        return tasks
    chosen = knapsack(candidates, end - first)
    selected = {t.id for t in chosen}
    return chosen + [t for t in tasks if t.id not in selected]
