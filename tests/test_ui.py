import gc
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from blackout_planner.domain import Device, Task
from blackout_planner.instance import SingleInstance
from blackout_planner.responsive import fit_window
from blackout_planner.storage import Store, import_week
from blackout_planner.theme import icon
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
    for widget in list(instance.topLevelWidgets()):
        if isinstance(widget, MainWindow):
            widget.allow_exit = True
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    instance.processEvents()
    gc.collect()


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


@pytest.fixture
def workspace_window(app, tmp_path):
    store = Store(tmp_path / "planner.sqlite3")
    store.set("week", [[True] * 48 for _ in range(7)])
    device = Device("Пристрій", power=100, interruptible=True)
    store.save(device)
    clock = {"now": datetime(2026, 11, 16, 12, tzinfo=ZoneInfo("Europe/Kyiv"))}
    task = Task(
        device.id,
        "Побутова задача",
        60,
        (clock["now"] + timedelta(hours=6)).isoformat(),
        interruptible=True,
    )
    store.save(task)
    window = MainWindow(store, lambda: clock["now"])
    window.timer.stop()
    window.show()
    wait_plan(app, window)
    yield window, store, device, task, clock
    QThreadPool.globalInstance().waitForDone()
    app.processEvents()
    window.allow_exit = True
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    store.close()


def test_dragging_timeline_persists_and_unlocks(app, workspace_window):
    window, store, _, task, _ = workspace_window
    timeline = window.timeline
    window.cards_scroll.ensureWidgetVisible(window.timeline_panel)
    app.processEvents()
    timeline.repaint()
    rect, segment = timeline.hits[0]
    begin = rect.center().toPoint()
    delta = round((timeline.width() - 150) / 24)
    end = begin + QPoint(delta, 0)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=begin)
    QTest.mouseMove(timeline, end)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=end)
    wait_plan(app, window)
    locked = store.tasks()[0]
    assert locked.locked_segments
    assert datetime.fromisoformat(locked.locked_segments[0][0]) == segment.start + timedelta(
        hours=1
    )
    window.unlock_task(locked)
    wait_plan(app, window)
    assert not store.tasks()[0].locked_segments


def test_invalid_drag_does_not_change_task(app, workspace_window, monkeypatch):
    window, store, _, _, _ = workspace_window
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    window.move_segment(window.plan.segments[0], -60)
    assert warnings
    assert not store.tasks()[0].locked_segments


def test_emergency_outage_pauses_and_replans_remainder(app, workspace_window):
    window, store, _, task, clock = workspace_window
    window.task_action(task, "running")
    wait_plan(app, window)
    clock["now"] += timedelta(minutes=10)
    window.apply_power_change(
        {
            "start": clock["now"].isoformat(),
            "end": (clock["now"] + timedelta(hours=1)).isoformat(),
            "power": False,
        }
    )
    wait_plan(app, window)
    saved = store.tasks()[0]
    assert saved.status == "paused" and saved.completed == 10
    assert window.plan.segments[0].start == clock["now"] + timedelta(hours=1)


def test_reserve_panel_changes_actual_plan(app, workspace_window):
    window, store, _, _, _ = workspace_window
    store.set("week", [[False] * 48 for _ in range(7)])
    panel = window.reserve_panel
    panel.enabled.setChecked(True)
    panel.compatible.item(0).setCheckState(Qt.CheckState.Checked)
    panel.simulation.item(0).setCheckState(Qt.CheckState.Checked)
    panel.save()
    wait_plan(app, window)
    assert not window.plan.conflicts
    assert window.plan.reserve_used_wh > 100
    assert "автономність" in panel.result.text()


def test_notification_history_prevents_duplicate_alerts(app, workspace_window):
    window, store, _, _, clock = workspace_window
    week = store.get("week")
    week[0][25] = False
    store.set("week", week)
    window.startup_notice = False
    window.last_check = clock["now"] - timedelta(seconds=30)
    window.process_notices()
    entries = store.get("notification_inbox")
    count = len(entries)
    assert any("Наближається" in entry["title"] for entry in entries)
    window.last_check = clock["now"] - timedelta(seconds=30)
    window.process_notices()
    assert len(store.get("notification_inbox")) == count


def test_resume_does_not_count_sleep_as_work(app, workspace_window):
    window, store, _, task, clock = workspace_window
    window.task_action(task, "running")
    wait_plan(app, window)
    window.last_tick = clock["now"] + timedelta(minutes=5)
    clock["now"] += timedelta(hours=2)
    window.tick()
    wait_plan(app, window)
    saved = store.tasks()[0]
    assert saved.status == "paused" and saved.completed == 5


def test_inbox_action_moves_current_task(app, workspace_window):
    window, store, _, task, clock = workspace_window
    window.handle_notice_action(task.id, "tomorrow")
    wait_plan(app, window)
    assert (
        datetime.fromisoformat(store.tasks()[0].deadline).date()
        == (clock["now"] + timedelta(days=1)).date()
    )


def test_confirmed_reserve_consumption_is_not_reused(app, workspace_window):
    window, store, device, task, clock = workspace_window
    store.set("week", [[False] * 48 for _ in range(7)])
    store.set(
        "battery",
        dict(
            capacity_wh=1000,
            charge=80,
            reserve=20,
            output_w=500,
            efficiency=1,
            compatible_ids=[device.id],
            enabled=True,
        ),
    )
    window.task_action(task, "running")
    wait_plan(app, window)
    clock["now"] += timedelta(minutes=30)
    snapshot = window.planning_arguments()
    assert snapshot["battery"].charge == pytest.approx(75)
    window.task_action(store.tasks()[0], "paused")
    wait_plan(app, window)
    assert store.get("battery")["charge"] == pytest.approx(75)
    assert window.planning_arguments()["battery"].charge == pytest.approx(75)


def test_single_instance_reopens_existing_process(app, tmp_path):
    import subprocess
    import sys

    first = SingleInstance(tmp_path)
    activations = []
    first.activated.connect(lambda: activations.append(True))
    assert first.acquire()
    try:
        code = (
            "import sys; from pathlib import Path; from PySide6.QtCore import QCoreApplication; "
            "from blackout_planner.instance import SingleInstance; app=QCoreApplication([]); "
            "instance=SingleInstance(Path(sys.argv[1])); sys.exit(1 if instance.acquire() else 0)"
        )
        caller = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)])
        deadline = time.monotonic() + 5
        while caller.poll() is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert activations
        assert caller.wait(timeout=2) == 0
    finally:
        first.release()


@pytest.mark.parametrize("width,height", [(1024, 600), (800, 600), (640, 480)])
def test_small_windows_keep_all_pages_reachable(app, workspace_window, width, height):
    window, _, _, _, _ = workspace_window
    window.resize(width, height)
    app.processEvents()
    assert window.width() == width and window.height() == height
    assert window.sidebar.width() == 76
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        assert window.width() == width and window.height() == height
        page = window.tabs.widget(index)
        assert page.viewport().width() > 0 and page.viewport().height() > 0
    window.tabs.setCurrentIndex(0)
    window.cards_scroll.ensureWidgetVisible(window.timeline_panel)
    app.processEvents()
    assert window.cards_scroll.verticalScrollBar().value() > 0


@pytest.mark.parametrize(
    "bounds", [QRect(0, 0, 800, 600), QRect(-1280, 0, 1280, 720), QRect(0, 0, 480, 360)]
)
def test_window_sizing_respects_work_area_and_monitor_origin(app, bounds):
    dialog = DeviceDialog()
    fit_window(dialog, bounds=bounds)
    assert bounds.contains(dialog.geometry())
    assert dialog.minimumWidth() <= dialog.width()
    assert dialog.minimumHeight() <= dialog.height()
    dialog.close()


def test_startup_window_fits_available_screen(app, workspace_window):
    window, _, _, _, _ = workspace_window
    assert window.screen().availableGeometry().contains(window.frameGeometry())


def test_main_window_and_navigation_fit_tiny_work_area(app, workspace_window):
    window, _, _, _, _ = workspace_window
    bounds = QRect(0, 0, 480, 360)
    fit_window(window, bounds=bounds)
    app.processEvents()
    assert bounds.contains(window.frameGeometry())
    assert window.sidebar.rect().contains(window.nav_group.button(5).geometry())


def test_onboarding_fits_small_screen(app, tmp_path):
    store = Store(tmp_path / "small-wizard.sqlite3")
    wizard = Onboarding(store, lambda: datetime.now(ZoneInfo("Europe/Kyiv")))
    bounds = QRect(0, 0, 640, 480)
    fit_window(wizard, (1000, 720), (480, 360), bounds)
    wizard.show()
    app.processEvents()
    assert bounds.contains(wizard.frameGeometry())
    wizard.schedule.editor.week = [[True] * 48 for _ in range(7)]
    for _ in range(3):
        wizard.next()
        app.processEvents()
        assert bounds.contains(wizard.frameGeometry())
    wizard.reject()
    wizard.deleteLater()
    store.close()


def test_sidebar_toggle_preserves_choice_and_centers_logo(app, workspace_window):
    window, store, _, _, _ = workspace_window
    for expected in (False, True):
        QTest.mouseClick(window.sidebar_toggle, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert window.sidebar_collapsed is expected
        assert store.get("sidebar_collapsed") is expected
        assert window.sidebar.width() == (76 if expected else 205)
        center = window.brand_mark.geometry().center().x()
        assert abs(center - window.sidebar.rect().center().x()) <= 1
        window.resize(900 if expected else 700, 600)
        app.processEvents()
        assert window.sidebar_collapsed is expected
    assert window.sidebar_toggle.accessibleName() == "Розгорнути меню"


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 2, 3])
def test_vector_icons_render_at_native_display_density(app, scale):
    from PySide6.QtCore import QSize

    image = icon("bolt", "#c8ed9b").pixmap(QSize(32, 32), scale)
    assert image.width() == round(32 * scale)
    assert image.height() == round(32 * scale)
    assert image.devicePixelRatioF() == pytest.approx(scale)
    assert not image.toImage().isNull()


def test_terracotta_themes_switch_without_losing_data(app, workspace_window):
    from PySide6.QtGui import QPalette

    from blackout_planner.appearance import DARK, LIGHT

    window, store, _, task, _ = workspace_window
    window.appearance.setCurrentIndex(1)
    wait_plan(app, window)
    assert store.get("appearance") == "dark"
    assert app.palette().color(QPalette.ColorRole.Window).name().upper() == DARK["background"]
    assert store.tasks()[0].id == task.id
    window.appearance.setCurrentIndex(0)
    wait_plan(app, window)
    assert app.palette().color(QPalette.ColorRole.Window).name().upper() == LIGHT["background"]


def test_day_lead_distinguishes_user_confirmation_from_forecast(app, workspace_window):
    window, _, _, _, clock = workspace_window
    assert "ГРАФІКОМ" in window.lead_source.text()
    window.apply_power_change(
        {
            "start": clock["now"].isoformat(),
            "end": (clock["now"] + timedelta(hours=1)).isoformat(),
            "power": False,
        }
    )
    wait_plan(app, window)
    assert window.lead_source.text() == "ПІДТВЕРДЖЕНО ВАМИ"
    assert "немає світла" in window.lead_title.text()


def test_deadline_editor_replans_existing_task(app, workspace_window, monkeypatch):
    from PySide6.QtWidgets import QDateTimeEdit

    window, store, _, task, clock = workspace_window

    def choose_deadline(dialog):
        dialog.findChild(QDateTimeEdit).setDateTime(
            (clock["now"] + timedelta(hours=8)).replace(tzinfo=None)
        )
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", choose_deadline)
    window.change_deadline(task)
    wait_plan(app, window)
    saved = store.tasks()[0]
    assert saved.id == task.id
    assert datetime.fromisoformat(saved.deadline) == clock["now"] + timedelta(hours=8)
