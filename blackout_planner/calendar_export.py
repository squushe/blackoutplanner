"""Експорт знімка розкладу в iCalendar RFC 5545."""

from datetime import UTC, datetime


def text(value):
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(c for c in value if c == "\n" or ord(c) >= 32)
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line):
    parts, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += char
    return "\r\n".join([*parts, current])


def export_ics(plan, tasks, now=None):
    now = now or datetime.now(UTC)
    names = {task.id: task.name for task in tasks}
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Blackout Planner//Schedule//UK",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    counters = {}
    for segment in sorted(plan.segments, key=lambda item: (item.task_id, item.start)):
        index = counters.get(segment.task_id, 0)
        counters[segment.task_id] = index + 1
        lines.extend([
            "BEGIN:VEVENT", f"UID:{segment.task_id}-{index}@blackout-planner.local",
            "DTSTAMP:" + now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "DTSTART:" + segment.start.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "DTEND:" + segment.end.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "SUMMARY:" + text(names.get(segment.task_id, "Побутова задача")),
            "DESCRIPTION:" + text("План за графіком електропостачання. Виконання підтверджує користувач."),
            "STATUS:TENTATIVE", "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold(line) for line in lines) + "\r\n").encode("utf-8")
