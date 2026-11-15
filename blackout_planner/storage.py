"""Транзакційне локальне сховище та імпорт графіка."""

import csv
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .domain import Device, Task, blank_week, validate_week


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            PRAGMA user_version=1;
        """)

    def get(self, key, default=None):
        row = self.connection.execute("SELECT payload FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def devices(self):
        return [
            Device(**json.loads(row[0]))
            for row in self.connection.execute("SELECT payload FROM devices ORDER BY rowid")
        ]

    def tasks(self):
        return [
            Task(**json.loads(row[0]))
            for row in self.connection.execute("SELECT payload FROM tasks ORDER BY rowid")
        ]

    def save(self, value: Device | Task):
        value.validate()
        table = "devices" if isinstance(value, Device) else "tasks"
        with self.connection:
            self.connection.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
                (value.id, json.dumps(asdict(value), ensure_ascii=False)),
            )

    def close(self):
        self.connection.close()


def time_minutes(value, allow_end=False):
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError("Час має бути у форматі HH:MM")
    hour, minute = map(int, parts)
    if allow_end and hour == 24 and minute == 0:
        return 1440
    if not 0 <= hour <= 23 or minute not in {0, 30}:
        raise ValueError("Час має бути кратним 30 хвилинам, від 00:00 до 24:00")
    return hour * 60 + minute


def import_week(path: str):
    """Формат: day (0=Пн), start, end, power (0/1); повний тиждень."""
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = (
            json.load(stream) if source.suffix.lower() == ".json" else list(csv.DictReader(stream))
        )
    if not isinstance(rows, list):
        raise ValueError("JSON має містити список інтервалів")
    week = blank_week()
    for row in rows:
        day = int(row["day"])
        if not 0 <= day <= 6:
            raise ValueError("День тижня має бути від 0 (Пн) до 6 (Нд)")
        start, end = time_minutes(row["start"]), time_minutes(row["end"], True)
        raw = row["power"]
        if str(raw).lower() not in {"0", "1", "true", "false"}:
            raise ValueError("Стан power має бути 0 або 1")
        power = str(raw).lower() in {"1", "true"}
        if start == end:
            raise ValueError("Порожній інтервал графіка")
        slots = [(day, k) for k in range(start // 30, (end if end > start else 1440) // 30)]
        if end < start:
            slots.extend(((day + 1) % 7, k) for k in range(end // 30))
        for d, k in slots:
            if week[d][k] is not None:
                raise ValueError("Інтервали перетинаються")
            week[d][k] = power
    validate_week(week)
    return week
