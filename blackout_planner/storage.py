"""Транзакційне локальне сховище та імпорт графіка."""

import csv
import json
import sqlite3
from datetime import UTC, datetime
from dataclasses import asdict
from pathlib import Path

from .domain import BatteryProfile, Device, Task, blank_week, validate_week


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()
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

    def backup(self, destination: Path):
        """SQLite backup включає підтверджені дані з WAL."""
        destination = destination.resolve()
        if destination == self.path or str(destination) in {str(self.path) + "-wal", str(self.path) + "-shm"}:
            raise ValueError("Резервна копія має бути окремим файлом")
        destination.parent.mkdir(parents=True, exist_ok=True)
        from uuid import uuid4
        temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
        try:
            with sqlite3.connect(temporary) as target:
                self.connection.backup(target)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def restore(self, source: Path):
        """Спочатку валідація і страхова копія, потім транзакційна заміна даних."""
        source = source.resolve()
        if source == self.path or not source.is_file():
            raise ValueError("Оберіть наявну резервну копію, відмінну від робочої бази")
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as backup:
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Резервна копія пошкоджена")
            if backup.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Непідтримувана версія бази")
            records = {}
            for table in ("devices", "tasks", "settings"):
                records[table] = backup.execute(f"SELECT * FROM {table}").fetchall()
            for _, payload in records["devices"]:
                Device(**json.loads(payload)).validate()
            for _, payload in records["tasks"]:
                Task(**json.loads(payload)).validate()
            settings = {key: json.loads(payload) for key, payload in records["settings"]}
            if "week" in settings:
                validate_week(settings["week"])
            if "battery" in settings:
                BatteryProfile(**settings["battery"]).validate()
        from uuid import uuid4
        safety = self.path.with_name("before-restore-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-")
                                     + uuid4().hex[:6] + ".sqlite3")
        self.backup(safety)
        with self.connection:
            for table, rows in records.items():
                self.connection.execute(f"DELETE FROM {table}")
                self.connection.executemany(f"INSERT INTO {table} VALUES (?,?)", rows)
        return safety


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
