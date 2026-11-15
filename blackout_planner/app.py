"""Точка входу десктопного застосунку."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QStandardPaths, QThreadPool
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .storage import Store
from .ui import MainWindow, Onboarding, configure_application


def main():
    parser = argparse.ArgumentParser(description="Blackout Planner")
    parser.add_argument("--data-dir", type=Path, help="Папка локальних даних")
    arguments = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("BlackoutPlanner")
    app.setOrganizationName("BlackoutPlanner")
    configure_application(app)
    folder = arguments.data_dir or Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )
    store = Store(folder / "planner.sqlite3")
    timezone = ZoneInfo(store.get("timezone", "Europe/Kyiv"))

    def now():
        return datetime.now(timezone)

    if not store.get("onboarded", False):
        wizard = Onboarding(store, now)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            store.close()
            return
    window = MainWindow(store, now)
    recovered = False
    for task in store.tasks():
        if task.status == "running":
            task.status = "paused"
            task.started_at = None
            store.save(task)
            recovered = True
    if recovered:
        window.replan()
    window.show()
    if recovered:
        QMessageBox.information(
            window,
            "Уточніть прогрес задач",
            "Перед виходом залишилися активні задачі. Вони призупинені. "
            "Непідтверджений час відсутності не зараховано. "
            "Підтвердіть завершення або продовжте роботу.",
        )
    app.exec()
    QThreadPool.globalInstance().waitForDone()
    store.close()


if __name__ == "__main__":
    main()
