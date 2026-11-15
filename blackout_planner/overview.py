"""Текстові підказки огляду дня без залежності від інтерфейсу."""

from datetime import UTC, timedelta

from .domain import minute_grid, power_at


def next_power_change(week, overrides, now):
    state = power_at(week, now, overrides)
    start = minute_grid(now.astimezone(UTC))
    if start <= now:
        start += timedelta(minutes=1)
    for minute in range(7 * 1440):
        moment = (start + timedelta(minutes=minute)).astimezone(now.tzinfo)
        changed = power_at(week, moment, overrides)
        if changed is not state:
            return moment, changed
    return None
