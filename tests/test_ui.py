import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QDialog

from blackout_planner.domain import Device
from blackout_planner.storage import Store, import_week
from blackout_planner.ui import (
    DeviceDialog,
    MainWindow,
    Onboarding,
    ScheduleEditor,
    TaskDialog,
    configure_application,
)


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    configure_application(instance)
    yield instance
    QThreadPool.globalInstance().waitForDone()


def wait_plan(app, window):
    deadline = time.monotonic() + 10
    while window.workers and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window.workers
    assert window.plan is not None


def test_schedule_editor_keeps_draft_separate(app):
    week = [[False] * 48 for _ in range(7)]
    editor = ScheduleEditor(week)
    editor.toggle(0, 0)
    assert editor.week[0][0] is True
    assert week[0][0] is False
    editor.close()


def test_device_and_task_forms(app):
    dialog = DeviceDialog()
    dialog.template.setCurrentText("Павербанк")
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    device = dialog.result_device
    assert device.kind == "battery"
    task = TaskDialog([device], datetime(2026, 11, 16, 12, tzinfo=ZoneInfo("Europe/Kyiv")))
    task.save()
    assert task.result_task.minutes == 157
    assert task.result_task.target == 100
    assert task.result_task.interruptible


def test_onboarding_persists_only_after_finish(app, tmp_path):
    store = Store(tmp_path / "wizard.sqlite3")
    wizard = Onboarding(store, lambda: datetime.now(ZoneInfo("Europe/Kyiv")))
    wizard.schedule.editor.week = [[True] * 48 for _ in range(7)]
    wizard.devices.append(Device("Ноутбук", kind="battery"))
    assert store.devices() == []
    assert store.get("onboarded") is None
    wizard.accept()
    assert store.get("onboarded") is True
    assert len(store.devices()) == 1
    store.close()


def test_window_calculates_and_displays_imported_schedule(app, tmp_path):
    store = Store(tmp_path / "window.sqlite3")
    store.set("week", import_week("examples/week.csv"))
    device = Device("Павербанк", kind="battery", power=20)
    store.save(device)
    now = datetime(2026, 11, 16, 12, tzinfo=ZoneInfo("Europe/Kyiv"))
    dialog = TaskDialog([device], now)
    dialog.save()
    store.save(dialog.result_task)
    window = MainWindow(store, lambda: now)
    window.show()
    wait_plan(app, window)
    assert len(window.plan.segments) == 1
    assert window.cards.count() == 1
    assert "є світло" in window.status.text()
    window.task_action(store.tasks()[0], "running")
    wait_plan(app, window)
    assert store.tasks()[0].status == "running"
    window.task_action(store.tasks()[0], "done")
    wait_plan(app, window)
    assert store.tasks()[0].status == "done"
    assert store.devices()[0].charge == 100
    window.allow_exit = True
    window.close()
    store.close()
