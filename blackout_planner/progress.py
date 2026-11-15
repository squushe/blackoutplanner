"""Оцінка підтвердженого сеансу роботи та витрати резервної енергії."""

from datetime import UTC, datetime, timedelta

from .domain import power_at


def progress_since_start(task, device, week, overrides, until, battery):
    if not task.started_at:
        return 0, 0.0
    start = datetime.fromisoformat(task.started_at).astimezone(UTC)
    elapsed = min(
        task.remaining, max(0, int((until.astimezone(UTC) - start).total_seconds() // 60))
    )
    reserve_minutes = 0
    if battery.enabled and device.id in battery.compatible_ids:
        for minute in range(elapsed):
            moment = (start + timedelta(minutes=minute)).astimezone(until.tzinfo)
            if power_at(week, moment, overrides) is False:
                reserve_minutes += 1
    return elapsed, reserve_minutes * device.power / (60 * battery.efficiency)
