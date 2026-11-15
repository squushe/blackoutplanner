"""Точка входу десктопного застосунку."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QCoreApplication, QEvent, QStandardPaths, QThreadPool
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .instance import SingleInstance
from .storage import Store
from .ui import MainWindow, Onboarding, configure_application


def main():
    parser = argparse.ArgumentParser(description="Blackout Planner")
    parser.add_argument("--data-dir", type=Path, help="Папка локальних даних")
    parser.add_argument(
        "--background", action="store_true", help="Запустити у треї, якщо він доступний"
    )
    arguments = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("BlackoutPlanner")
    app.setOrganizationName("BlackoutPlanner")
    configure_application(app)
    folder = arguments.data_dir or Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )
    instance = SingleInstance(folder)
    if not instance.acquire(activate=not arguments.background):
        return
    store = Store(folder / "planner.sqlite3")

    def now():
        return datetime.now(ZoneInfo(store.get("timezone", "Europe/Kyiv")))

    if not store.get("onboarded", False):
        wizard = Onboarding(store, now)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            store.close()
            instance.release()
            return
    recovered = False
    for task in store.tasks():
        if task.status == "running":
            task.status = "paused"
            task.started_at = None
            store.save(task)
            recovered = True
    window = MainWindow(store, now)
    instance.activated.connect(window.show_from_tray)
    if not arguments.background or not window.tray.isVisible():
        window.show()
    app.applicationStateChanged.connect(lambda state: window.tick())
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
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    store.close()
    instance.release()


if __name__ == "__main__":
    main()
