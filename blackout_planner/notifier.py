"""Системний транспорт нагадувань із запасним відкриттям картки."""

import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtWidgets import QSystemTrayIcon


class Notifier(QObject):
    activated = Signal(str, str)

    def __init__(self, tray, parent=None):
        super().__init__(parent)
        self.tray = tray
        self.latest = ""
        self.processes = []
        self.notify_send = shutil.which("notify-send") if sys.platform.startswith("linux") else None
        self.actions = False
        if self.notify_send:
            try:
                help_text = subprocess.run(
                    [self.notify_send, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                ).stdout
                self.actions = "--action" in help_text and "--wait" in help_text
            except (OSError, subprocess.TimeoutExpired):
                self.notify_send = None
        tray.messageClicked.connect(lambda: self.activated.emit(self.latest, "open"))

    def send(self, notice):
        task_id = notice.object_id.split(":")[0] if notice.kind in {"conflict", "finish"} else ""
        self.latest = task_id
        if self.notify_send:
            process = QProcess(self)
            arguments = ["--app-name=Blackout Planner", "--icon=dialog-information"]
            if self.actions:
                arguments += ["--wait", "--action=open=Відкрити план"]
                if notice.kind == "conflict":
                    arguments += ["--action=tomorrow=Перенести на завтра"]
                if notice.kind == "finish":
                    arguments += ["--action=done=Підтвердити виконання"]
            arguments += ["--", notice.title, notice.body]
            self.processes.append(process)

            def finished(*args):
                action = bytes(process.readAllStandardOutput()).decode().strip()
                if action in {"open", "tomorrow", "done"}:
                    self.activated.emit(task_id, action)
                elif process.exitCode() and self.tray.isVisible():
                    self.tray.showMessage(notice.title, notice.body)
                if process in self.processes:
                    self.processes.remove(process)
                process.deleteLater()

            process.finished.connect(finished)
            process.start(self.notify_send, arguments)
        elif self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(notice.title, notice.body)

    def shutdown(self):
        for process in self.processes[:]:
            process.kill()
            process.waitForFinished(1000)
