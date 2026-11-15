"""Інтерфейс Blackout Planner на Qt Widgets."""

import copy
import json
import math
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from .calendar_export import export_ics
from .domain import BatteryProfile, Device, Task, blank_week, build_plan, power_at, validate_week
from .notifications import Notice, build_notices, due_notices, upcoming_text
from .notifier import Notifier
from .panels import OutageDialog, ReservePanel
from .platform_services import Autostart
from .progress import progress_since_start
from .storage import import_week
from .theme import STYLE, icon


def configure_application(app):
    app.setStyle("Fusion")
    # Offscreen-платформа може не знаходити системні шрифти у Windows.
    if not QFontDatabase.families():
        font = Path("C:/Windows/Fonts/segoeui.ttf")
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, "#f4f7f6"),
        (QPalette.ColorRole.WindowText, "#243b38"),
        (QPalette.ColorRole.Base, "#ffffff"),
        (QPalette.ColorRole.AlternateBase, "#f1f6f1"),
        (QPalette.ColorRole.Text, "#243b38"),
        (QPalette.ColorRole.Button, "#ffffff"),
        (QPalette.ColorRole.ButtonText, "#3e5d50"),
        (QPalette.ColorRole.Highlight, "#528760"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
    ]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


def button(text, callback, layout):
    value = QPushButton(text)
    value.setCursor(Qt.CursorShape.PointingHandCursor)
    value.clicked.connect(callback)
    layout.addWidget(value)
    return value


def number(minimum, maximum, value, suffix="", decimals=None):
    widget = QSpinBox() if decimals is None else QDoubleSpinBox()
    if decimals is not None:
        widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setSuffix(suffix)
    return widget


class ScheduleEditor(QWidget):
    changed = Signal()

    def __init__(self, week):
        super().__init__()
        self.week = copy.deepcopy(week)
        layout = QVBoxLayout(self)
        label = QLabel(
            "Клік по клітинці: невідомо → є світло → немає світла. "
            "Виділіть діапазон і застосуйте стан кнопкою."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        actions = QHBoxLayout()
        button("Є світло", lambda: self.fill(True), actions)
        button("Немає світла", lambda: self.fill(False), actions)
        button("Увесь тиждень: є світло", lambda: self.fill(True, True), actions)
        button("Імпорт JSON / CSV", self.import_file, actions)
        layout.addLayout(actions)
        self.table = QTableWidget(48, 7)
        self.table.setHorizontalHeaderLabels(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"])
        self.table.setVerticalHeaderLabels([f"{k // 2:02}:{(k % 2) * 30:02}" for k in range(48)])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.cellClicked.connect(self.toggle)
        layout.addWidget(self.table)
        self.render()

    def render(self):
        for day in range(7):
            for slot in range(48):
                value = self.week[day][slot]
                item = QTableWidgetItem(
                    "Є" if value is True else "Немає" if value is False else "?"
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(
                    QColor(
                        "#dcefdc" if value is True else "#eef1ef" if value is False else "#fff3d8"
                    )
                )
                item.setForeground(QColor("#427450" if value is True else "#7f8e85"))
                self.table.setItem(slot, day, item)
        self.changed.emit()

    def toggle(self, row, column):
        self.week[column][row] = self.week[column][row] is not True
        self.render()

    def fill(self, power, all_week=False):
        if all_week:
            self.week = [[power] * 48 for _ in range(7)]
        else:
            for index in self.table.selectedIndexes():
                self.week[index.column()][index.row()] = power
        self.render()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Імпорт графіка", "", "Графік (*.json *.csv)")
        if not path:
            return
        try:
            week = import_week(path)
            powered = sum(value for day in week for value in day) / 2
            reply = QMessageBox.question(
                self,
                "Попередній перегляд",
                f"Прочитано повний тиждень.\n"
                f"З живленням: {powered:g} год.\nЗамінити графік у редакторі?",
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.week = week
                self.render()
        except (ValueError, KeyError, TypeError, OSError) as error:
            QMessageBox.warning(self, "Імпорт не виконано", str(error))


TEMPLATES = {
    "Власний пристрій": ("job", 100, 60, 74, 40),
    "Павербанк": ("battery", 20, 60, 74, 40),
    "Ноутбук": ("battery", 65, 60, 60, 40),
    "Пральна машина": ("job", 2000, 90, 74, 40),
    "Бойлер": ("job", 1500, 60, 74, 40),
    "Індукційна плита": ("job", 1800, 30, 74, 40),
}


class DeviceDialog(QDialog):
    def __init__(self, parent=None, device=None):
        super().__init__(parent)
        self.setWindowTitle("Редагування пристрою" if device else "Новий пристрій")
        self.setMinimumWidth(470)
        self.device = device
        self.result_device = None
        form = QFormLayout(self)
        self.template = QComboBox()
        self.template.addItems(TEMPLATES)
        form.addRow("Шаблон", self.template)
        self.name = QLineEdit()
        form.addRow("Назва", self.name)
        self.kind = QComboBox()
        self.kind.addItems(["Одноразова робота", "Накопичувач для заряджання"])
        form.addRow("Тип", self.kind)
        self.power = number(0.1, 100000, 100, " Вт", 1)
        self.duration = number(1, 10080, 60, " хв")
        self.interruptible = QCheckBox("Можна перервати та продовжити")
        self.capacity = number(0.1, 1000000, 74, " Вт·год", 1)
        self.charge = number(0, 100, 40, " %")
        self.efficiency = number(1, 100, 85, " %")
        self.priority = number(1, 5, 3)
        for title, widget in [
            ("Потужність / зарядний пристрій", self.power),
            ("Типова тривалість", self.duration),
            ("Переривання", self.interruptible),
            ("Ємність", self.capacity),
            ("Поточний заряд", self.charge),
            ("Ефективність заряджання", self.efficiency),
            ("Пріоритет (5 — найвищий)", self.priority),
        ]:
            form.addRow(title, widget)
        hint = QLabel(
            "Параметри шаблонів — приклади. Уточніть їх за своїм пристроєм.\n"
            "Для мА·год: Вт·год = мА·год × номінальна напруга / 1000."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Зберегти")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        form.addRow(buttons)
        self.template.currentTextChanged.connect(self.apply_template)
        self.kind.currentIndexChanged.connect(self.update_fields)
        if device:
            self.name.setText(device.name)
            self.kind.setCurrentIndex(device.kind == "battery")
            for widget, value in [
                (self.power, device.power),
                (self.duration, device.duration),
                (self.capacity, device.capacity),
                (self.charge, device.charge),
                (self.efficiency, device.efficiency * 100),
                (self.priority, device.priority),
            ]:
                widget.setValue(value)
            self.interruptible.setChecked(device.interruptible)
        self.update_fields()

    def update_fields(self):
        battery = self.kind.currentIndex() == 1
        self.duration.setEnabled(not battery)
        self.interruptible.setEnabled(not battery)
        for widget in (self.capacity, self.charge, self.efficiency):
            widget.setEnabled(battery)

    def apply_template(self, name):
        kind, power, duration, capacity, charge = TEMPLATES[name]
        self.name.setText("" if name == "Власний пристрій" else name)
        self.kind.setCurrentIndex(kind == "battery")
        self.power.setValue(power)
        self.duration.setValue(duration)
        self.capacity.setValue(capacity)
        self.charge.setValue(charge)

    def save(self):
        value = Device(
            self.name.text().strip(),
            "battery" if self.kind.currentIndex() else "job",
            self.power.value(),
            self.duration.value(),
            self.interruptible.isChecked(),
            self.capacity.value(),
            self.charge.value(),
            self.efficiency.value() / 100,
            self.priority.value(),
        )
        if self.device:
            value.id = self.device.id
        try:
            value.validate()
        except ValueError as error:
            QMessageBox.warning(self, "Перевірте параметри", str(error))
            return
        self.result_device = value
        self.accept()


class TaskDialog(QDialog):
    def __init__(self, devices, now, parent=None):
        super().__init__(parent)
        self.devices = devices
        self.now = now
        self.result_task = None
        self.setWindowTitle("Нова задача")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.device = QComboBox()
        self.device.addItems([d.name for d in devices])
        self.name = QLineEdit()
        self.minutes = number(1, 10080, 60, " хв")
        self.target = number(1, 100, 100, " %")
        self.priority = number(1, 5, 3)
        self.interruptible = QCheckBox("Можна переривати")
        self.deadline = QDateTimeEdit(now.replace(tzinfo=None) + timedelta(hours=6))
        self.deadline.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.deadline.setCalendarPopup(True)
        for label, widget in [
            ("Пристрій", self.device),
            ("Задача", self.name),
            ("Тривалість", self.minutes),
            ("Цільовий заряд", self.target),
            ("Дедлайн", self.deadline),
            ("Пріоритет", self.priority),
            ("Переривання", self.interruptible),
        ]:
            form.addRow(label, widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Зберегти")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        form.addRow(buttons)
        self.device.currentIndexChanged.connect(self.select_device)
        self.target.valueChanged.connect(self.update_estimate)
        self.select_device(0)

    def select_device(self, index):
        device = self.devices[index]
        battery = device.kind == "battery"
        self.name.setText(("Зарядити: " if battery else "Виконати: ") + device.name)
        self.minutes.setValue(device.duration)
        self.minutes.setEnabled(not battery)
        self.target.setEnabled(battery)
        self.priority.setValue(device.priority)
        self.interruptible.setChecked(battery or device.interruptible)
        self.interruptible.setEnabled(not battery)
        self.update_estimate()

    def update_estimate(self):
        device = self.devices[self.device.currentIndex()]
        if device.kind == "battery":
            self.minutes.setValue(device.charging_minutes(self.target.value()))

    def save(self):
        device = self.devices[self.device.currentIndex()]
        deadline = self.deadline.dateTime().toPython().replace(tzinfo=self.now.tzinfo)
        if not self.name.text().strip() or deadline <= self.now:
            QMessageBox.warning(self, "Перевірте задачу", "Введіть назву й майбутній дедлайн")
            return
        minutes = (
            device.charging_minutes(self.target.value())
            if device.kind == "battery"
            else self.minutes.value()
        )
        if minutes == 0:
            QMessageBox.information(
                self, "Ціль уже досягнута", "Уточніть поточний або цільовий заряд"
            )
            return
        self.result_task = Task(
            device.id,
            self.name.text().strip(),
            minutes,
            deadline.isoformat(),
            self.priority.value(),
            self.interruptible.isChecked(),
            target=self.target.value() if device.kind == "battery" else None,
        )
        self.accept()


class SchedulePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("1. Графік електропостачання")
        self.editor = ScheduleEditor(blank_week())
        QVBoxLayout(self).addWidget(self.editor)

    def validatePage(self):
        try:
            validate_week(self.editor.week)
            return True
        except ValueError as error:
            QMessageBox.warning(self, "Графік не заповнений", str(error))
            return False


class Onboarding(QWizard):
    def __init__(self, store, now):
        super().__init__()
        self.store = store
        self.now = now
        self.devices = []
        self.tasks = []
        self.setWindowTitle("Ласкаво просимо до Blackout Planner")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.resize(1050, 760)
        self.setButtonText(QWizard.WizardButton.NextButton, "Далі")
        self.setButtonText(QWizard.WizardButton.BackButton, "Назад")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Побудувати розклад")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Скасувати")
        self.schedule = SchedulePage()
        self.addPage(self.schedule)
        devices = QWizardPage()
        devices.setTitle("2. Додайте свої пристрої")
        layout = QVBoxLayout(devices)
        label = QLabel(
            "Оберіть шаблон або введіть параметри власного пристрою. "
            "Додавання пристрою ще не запускає задачу."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.device_list = QListWidget()
        layout.addWidget(self.device_list)
        button("+ Додати пристрій", self.add_device, layout)
        self.addPage(devices)
        priorities = QWizardPage()
        priorities.setTitle("3. Пріоритети та початкові задачі")
        layout = QVBoxLayout(priorities)
        label = QLabel(
            "Пріоритет 5 — найвищий; типове значення — 3. "
            "Вкажіть потрібні дії та дедлайни. Цей крок можна пропустити."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.task_list = QListWidget()
        layout.addWidget(self.task_list)
        button("+ Додати початкову задачу", self.add_task, layout)
        self.addPage(priorities)
        options = QWizardPage()
        options.setTitle("4. Нагадування та завершення")
        layout = QVBoxLayout(options)
        self.notifications = QCheckBox("Сповіщати за 30 і 10 хвилин до відключення")
        self.notifications.setChecked(True)
        layout.addWidget(self.notifications)
        self.autostart = Autostart(store.path.parent)
        self.autostart_checkbox = QCheckBox("Запускати Blackout Planner разом із системою")
        self.autostart_checkbox.setChecked(self.autostart.enabled())
        if self.autostart.last_error:
            self.autostart_checkbox.setEnabled(False)
            self.autostart_checkbox.setToolTip(self.autostart.last_error)
        layout.addWidget(self.autostart_checkbox)
        label = QLabel(
            "Застосунок працює локально. Закриття вікна залишає його в треї, "
            "якщо трей доступний. Для припинення роботи оберіть «Вихід».\n\n"
            "Сповіщення залежать від налаштувань ОС. Фактичне живлення та прогрес "
            "ви підтверджуєте самі. Клік по системному повідомленню відкриває план; "
            "усі нагадування також зберігаються у вкладці «Сповіщення»."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        layout.addStretch()
        self.addPage(options)
        self.currentIdChanged.connect(self.update_summary)

    def add_device(self):
        dialog = DeviceDialog(self)
        if dialog.exec():
            device = dialog.result_device
            self.devices.append(device)
            self.device_list.addItem(
                f"{device.name} · {device.power:g} Вт · пріоритет {device.priority}"
            )

    def add_task(self):
        if not self.devices:
            QMessageBox.information(self, "Додайте пристрій", "Поверніться на попередній крок")
            return
        dialog = TaskDialog(self.devices, self.now(), self)
        if dialog.exec():
            task = dialog.result_task
            self.tasks.append(task)
            self.task_list.addItem(f"{task.name} · {task.minutes} хв · пріоритет {task.priority}")

    def update_summary(self):
        self.summary.setText(
            f"Пристроїв: {len(self.devices)}. Початкових задач: {len(self.tasks)}."
        )

    def accept(self):
        try:
            if self.autostart_checkbox.isChecked() != self.autostart.enabled():
                self.autostart.set_enabled(self.autostart_checkbox.isChecked())
        except OSError as error:
            QMessageBox.warning(self, "Автозапуск не змінено", str(error))
            return
        for value in [*self.devices, *self.tasks]:
            self.store.save(value)
        self.store.set("week", self.schedule.editor.week)
        self.store.set("notifications", self.notifications.isChecked())
        self.store.set("onboarded", True)
        super().accept()


class Timeline(QWidget):
    move_requested = Signal(object, int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(140)
        self.setMinimumWidth(650)
        self.plan = None
        self.tasks = []
        self.week = blank_week()
        self.now = datetime.now().astimezone()
        self.overrides = []
        self.hits = []
        self.drag = None
        self.setMouseTracking(True)
        self.setToolTip("Перетягніть сегмент задачі. Крок переміщення — 5 хвилин.")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for rect, segment in self.hits:
                if rect.contains(event.position()):
                    task = next(t for t in self.tasks if t.id == segment.task_id)
                    if task.status != "running":
                        self.drag = (segment, event.position().x(), event.position().x())
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    break

    def mouseMoveEvent(self, event):
        if self.drag:
            self.drag = (*self.drag[:2], event.position().x())
            self.update()
        else:
            hit = next(
                (segment for rect, segment in self.hits if rect.contains(event.position())), None
            )
            self.setCursor(Qt.CursorShape.OpenHandCursor if hit else Qt.CursorShape.ArrowCursor)
            if hit:
                self.setToolTip(
                    f"{hit.start.astimezone(self.now.tzinfo):%H:%M}–"
                    f"{hit.end.astimezone(self.now.tzinfo):%H:%M}. Перетягніть для зміни часу."
                )

    def mouseReleaseEvent(self, event):
        if self.drag:
            segment, first_x, _ = self.drag
            delta = round((event.position().x() - first_x) / (self.width() - 150) * 1440 / 5) * 5
            self.drag = None
            self.unsetCursor()
            if delta:
                self.move_requested.emit(segment, delta)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() - 150
        left = 115
        painter.fillRect(self.rect(), QColor("#ffffff"))
        self.hits = []
        day = self.now.replace(hour=0, minute=0, second=0, microsecond=0)

        def x(value):
            local = value.astimezone(self.now.tzinfo)
            return left + width * ((local - day).total_seconds() / 86400)

        for slot in range(1440):
            power = power_at(self.week, day + timedelta(minutes=slot), self.overrides)
            painter.fillRect(
                int(left + width * slot / 1440),
                28,
                math.ceil(width / 1440),
                20,
                QColor("#b8dba1" if power is True else "#eef2ee"),
            )
        painter.setPen(QColor("#84998b"))
        for hour in range(0, 25, 3):
            position = int(left + width * hour / 24)
            painter.drawText(position - 12, 19, f"{hour:02}:00")
            painter.setPen(QPen(QColor("#e8efe8"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(position, 50, position, self.height() - 10)
            painter.setPen(QColor("#84998b"))
        painter.drawText(10, 43, "Живлення")
        for row, task in enumerate(self.tasks):
            y = 68 + row * 36
            painter.setPen(QColor("#5e7867"))
            painter.drawText(
                10,
                y + 17,
                painter.fontMetrics().elidedText(task.name, Qt.TextElideMode.ElideRight, 100),
            )
            if self.plan:
                for segment in self.plan.segments:
                    if segment.task_id != task.id:
                        continue
                    begin, end = max(left, x(segment.start)), min(left + width, x(segment.end))
                    if end > begin:
                        rect = QRectF(begin, y, max(2, end - begin), 23)
                        self.hits.append((rect, segment))
                        if self.drag and self.drag[0] == segment:
                            begin += self.drag[2] - self.drag[1]
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor("#e9c880" if task.locked_segments else "#79ab78"))
                        painter.drawRoundedRect(QRectF(begin, y, rect.width(), 23), 5, 5)
        painter.setPen(QPen(QColor("#3d7952"), 2))
        painter.drawLine(int(x(self.now)), 25, int(x(self.now)), self.height() - 8)


class WorkerSignals(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)


class PlanWorker(QRunnable):
    def __init__(self, revision, arguments):
        super().__init__()
        self.revision = revision
        self.arguments = arguments
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.ready.emit(self.revision, build_plan(**self.arguments))
        except Exception as error:
            self.signals.failed.emit(self.revision, str(error))


class MainWindow(QMainWindow):
    def __init__(self, store, now):
        super().__init__()
        self.store = store
        self.now = now
        self.revision = 0
        self.plan = None
        self.workers = {}
        self.last_check = now()
        self.last_tick = now()
        self.startup_notice = True
        self.current_notice = None
        self.autostart = Autostart(store.path.parent)
        self.allow_exit = False
        self.setWindowTitle("Blackout Planner")
        self.resize(1380, 920)
        self.setMinimumSize(1080, 760)
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 28, 18, 25)
        side.setSpacing(7)
        logo = QLabel()
        logo.setPixmap(icon("bolt", "#c8ed9b", 32).pixmap(32, 32))
        side.addWidget(logo)
        brand = QLabel("Blackout\nPlanner")
        brand.setObjectName("brand")
        side.addWidget(brand)
        tagline = QLabel("Планування під відключення")
        tagline.setWordWrap(True)
        tagline.setObjectName("brandSub")
        side.addWidget(tagline)
        side.addSpacing(32)
        caption = QLabel("РОБОЧИЙ ПРОСТІР")
        caption.setObjectName("navCaption")
        side.addWidget(caption)
        self.nav_group = QButtonGroup(self)
        self.page_names = [
            "План на сьогодні",
            "Графік живлення",
            "Мої пристрої",
            "Резерв та автономність",
            "Центр сповіщень",
            "Налаштування",
        ]
        for index, (name, glyph) in enumerate(
            zip(
                [
                    "Огляд дня",
                    "Графік живлення",
                    "Пристрої",
                    "Автономність",
                    "Сповіщення",
                    "Налаштування",
                ],
                ["today", "calendar", "devices", "battery", "bell", "settings"],
            )
        ):
            item = QPushButton(name)
            item.setObjectName("nav")
            item.setIcon(icon(glyph))
            item.setCheckable(True)
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(item, index)
            side.addWidget(item)
        self.nav_group.button(0).setChecked(True)
        side.addStretch()
        footer = QLabel("ОФЛАЙН-РЕЖИМ\n\nЛокально · без хмари")
        footer.setObjectName("brandSub")
        side.addWidget(footer)
        shell.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(16)
        shell.addWidget(content, 1)
        header = QHBoxLayout()
        self.page_title = QLabel(self.page_names[0])
        self.page_title.setObjectName("title")
        header.addWidget(self.page_title)
        header.addStretch()
        button("Уточнити світло", self.correct_power, header)
        button("+ Нова задача", self.add_task, header).setObjectName("primary")
        layout.addLayout(header)
        self.status = QLabel()
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        self.metrics_widget = QWidget()
        metrics = QHBoxLayout(self.metrics_widget)
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(14)
        self.metric_labels = []
        for caption, hint in [
            ("ЕЛЕКТРОПОСТАЧАННЯ", "За актуальним графіком"),
            ("ЗАДАЧІ НА ДЕНЬ", "У вашому плані"),
            ("РЕЗЕРВ ЕНЕРГІЇ", "Доступно вище мінімуму"),
        ]:
            card = QFrame()
            card.setObjectName("metric")
            box = QVBoxLayout(card)
            box.setContentsMargins(18, 16, 18, 16)
            box.setSpacing(6)
            name, value, description = QLabel(caption), QLabel("—"), QLabel(hint)
            name.setObjectName("metricCaption")
            value.setObjectName("metricValue")
            description.setObjectName("metricHint")
            for label in (name, value, description):
                box.addWidget(label)
            metrics.addWidget(card, 1)
            self.metric_labels.append((value, description))
        layout.addWidget(self.metrics_widget)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.nav_group.idClicked.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.navigate)
        layout.addWidget(self.tabs)
        today = QWidget()
        today_layout = QVBoxLayout(today)
        today_layout.setContentsMargins(0, 0, 0, 0)
        today_layout.setSpacing(14)
        timeline_panel = QFrame()
        self.timeline_panel = timeline_panel
        timeline_panel.setObjectName("timelinePanel")
        timeline_box = QVBoxLayout(timeline_panel)
        timeline_box.setContentsMargins(16, 16, 16, 12)
        timeline_heading = QHBoxLayout()
        title = QLabel("Розклад дня")
        title.setObjectName("sectionTitle")
        timeline_heading.addWidget(title)
        timeline_heading.addStretch()
        legend = QLabel(
            '<span style="color:#73a66a">●</span> Живлення　 '
            '<span style="color:#a7b5ab">●</span> Відключення　 ↔ Перетягніть задачу'
        )
        legend.setObjectName("muted")
        timeline_heading.addWidget(legend)
        timeline_box.addLayout(timeline_heading)
        self.timeline = Timeline()
        self.timeline.move_requested.connect(self.move_segment)
        timeline_scroll = QScrollArea()
        timeline_scroll.setWidgetResizable(True)
        timeline_scroll.setWidget(self.timeline)
        timeline_box.addWidget(timeline_scroll)
        today_layout.addWidget(timeline_panel, 1)
        task_heading = QHBoxLayout()
        title = QLabel("Ваші задачі")
        title.setObjectName("sectionTitle")
        task_heading.addWidget(title)
        task_heading.addStretch()
        self.task_count = QLabel()
        self.task_count.setObjectName("muted")
        task_heading.addWidget(self.task_count)
        today_layout.addLayout(task_heading)
        self.cards_widget = QWidget()
        self.cards = QVBoxLayout(self.cards_widget)
        self.cards.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.cards.setContentsMargins(0, 0, 6, 0)
        self.cards.setSpacing(12)
        self.cards.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.cards_widget)
        self.cards_scroll = scroll
        today_layout.addWidget(scroll, 2)
        self.tabs.addTab(today, "Сьогодні")
        self.editor = ScheduleEditor(store.get("week", blank_week()))
        schedule = QWidget()
        schedule_layout = QVBoxLayout(schedule)
        schedule_layout.addWidget(self.editor)
        button("Зберегти графік і перепланувати", self.save_week, schedule_layout)
        self.override_list = QListWidget()
        self.override_list.setMaximumHeight(100)
        schedule_layout.addWidget(self.override_list)
        override_actions = QHBoxLayout()
        button("+ Уточнення для дати", self.correct_power, override_actions)
        button("Видалити вибране уточнення", self.delete_override, override_actions)
        schedule_layout.addLayout(override_actions)
        self.tabs.addTab(schedule, "Графік")
        devices = QWidget()
        devices_layout = QVBoxLayout(devices)
        self.device_list = QListWidget()
        self.device_list.itemDoubleClicked.connect(self.edit_device)
        devices_layout.addWidget(self.device_list)
        actions = QHBoxLayout()
        button("+ Додати пристрій", self.add_device, actions)
        button("Редагувати вибраний", self.edit_device, actions)
        devices_layout.addLayout(actions)
        self.tabs.addTab(devices, "Пристрої")
        self.reserve_panel = ReservePanel(store)
        self.reserve_panel.saved.connect(self.replan)
        self.tabs.addTab(self.reserve_panel, "Автономність")
        inbox = QWidget()
        inbox_layout = QVBoxLayout(inbox)
        self.inbox = QListWidget()
        self.inbox.currentRowChanged.connect(self.select_notice)
        inbox_layout.addWidget(self.inbox)
        self.notice_detail = QLabel(
            "Нагадування зберігаються тут, навіть якщо ОС приховала повідомлення."
        )
        self.notice_detail.setWordWrap(True)
        inbox_layout.addWidget(self.notice_detail)
        actions = QHBoxLayout()
        self.notice_open = button(
            "Відкрити задачу / план", lambda: self.notice_action("open"), actions
        )
        self.notice_tomorrow = button(
            "Перенести на завтра", lambda: self.notice_action("tomorrow"), actions
        )
        self.notice_done = button(
            "Підтвердити виконання", lambda: self.notice_action("done"), actions
        )
        inbox_layout.addLayout(actions)
        self.tabs.addTab(inbox, "Сповіщення")
        settings = QWidget()
        form = QFormLayout(settings)
        self.power = number(1, 100000, store.get("power_limit", 3500), " Вт")
        self.background = number(0, 100000, store.get("background_power", 0), " Вт")
        form.addRow("Ліміт потужності мережі", self.power)
        form.addRow("Фонове споживання", self.background)
        self.notifications = QCheckBox("Увімкнути сповіщення")
        self.notifications.setChecked(store.get("notifications", True))
        form.addRow(self.notifications)
        self.autostart_checkbox = QCheckBox("Запускати Blackout Planner разом із системою")
        self.autostart_checkbox.setChecked(self.autostart.enabled())
        if self.autostart.last_error:
            self.autostart_checkbox.setEnabled(False)
            self.autostart_checkbox.setToolTip(self.autostart.last_error)
        form.addRow(self.autostart_checkbox)
        self.algorithm = QComboBox()
        self.algorithm.addItems(
            ["Базова евристика priority / EDF", "Евристика з локальною DP оптимізацією"]
        )
        self.algorithm.setCurrentIndex(self.store.get("algorithm", "greedy") == "dp")
        form.addRow("Алгоритм", self.algorithm)
        save = QPushButton("Зберегти налаштування")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        export = QPushButton("Експортувати поточний план у JSON")
        export.clicked.connect(self.export_plan)
        form.addRow(export)
        calendar = QPushButton("Експорт у календар ICS")
        calendar.clicked.connect(self.export_calendar)
        form.addRow(calendar)
        backup = QPushButton("Створити резервну копію")
        backup.clicked.connect(self.backup_data)
        form.addRow(backup)
        restore = QPushButton("Відновити резервну копію")
        restore.clicked.connect(self.restore_data)
        form.addRow(restore)
        note = QLabel(
            "Статус живлення визначається за введеним графіком.\n"
            "Підтверджуйте початок і завершення роботи на картках задач.\n"
            "Ручні закріплення позначені жовтим на таймлайні."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(settings, "Налаштування")
        self.tray = QSystemTrayIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self
        )
        self.setWindowIcon(self.tray.icon())
        menu = QMenu(self)
        show = QAction("Відкрити Blackout Planner", self)
        show.triggered.connect(self.show_from_tray)
        menu.addAction(show)
        exit_action = QAction("Вихід", self)
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_from_tray()
                if reason == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
        )
        self.notifier = Notifier(self.tray, self)
        self.notifier.activated.connect(self.handle_notice_action)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(30000)
        self.refresh_devices()
        self.refresh_overrides()
        self.refresh_inbox()
        self.replan()
        QTimer.singleShot(1000, self.tick)

    def navigate(self, index):
        self.page_title.setText(self.page_names[index])
        self.metrics_widget.setVisible(index == 0)
        self.nav_group.button(index).setChecked(True)

    def planning_arguments(self, tasks=None):
        values = self.store.tasks() if tasks is None else copy.deepcopy(tasks)
        now = self.now()
        battery = BatteryProfile(**self.store.get("battery", {}))
        week = self.store.get("week", blank_week())
        overrides = self.store.get("overrides", [])
        devices = self.store.devices()
        by_device = {device.id: device for device in devices}
        consumed = 0
        for task in values:
            if task.started_at and task.device_id in by_device:
                elapsed, energy = progress_since_start(
                    task, by_device[task.device_id], week, overrides, now, battery
                )
                task.completed = min(task.minutes, task.completed + elapsed)
                consumed += energy
        battery.charge = max(0, battery.charge - consumed / battery.capacity_wh * 100)
        return dict(
            devices=devices,
            tasks=values,
            week=week,
            now=now,
            power_limit=self.store.get("power_limit", 3500),
            background_power=self.store.get("background_power", 0),
            overrides=overrides,
            battery=battery,
            algorithm=self.store.get("algorithm", "greedy"),
        )

    def move_segment(self, segment, delta):
        if self.workers or not self.plan or segment not in self.plan.segments:
            self.statusBar().showMessage(
                "Дочекайтеся актуального розкладу й повторіть переміщення", 5000
            )
            return
        task = next(t for t in self.store.tasks() if t.id == segment.task_id)
        if task.status == "running":
            return
        future = [s for s in self.plan.segments if s.task_id == task.id]
        task.locked_segments = [
            [
                (s.start + timedelta(minutes=delta) if s == segment else s.start).isoformat(),
                (s.end + timedelta(minutes=delta) if s == segment else s.end).isoformat(),
            ]
            for s in future
        ]
        task.locked_segments.sort()
        tasks = [task if t.id == task.id else t for t in self.store.tasks()]
        trial = build_plan(**self.planning_arguments(tasks))
        new_conflicts = set(trial.conflicts) - set(self.plan.conflicts)
        if task.id in trial.conflicts or new_conflicts:
            message = trial.conflicts.get(task.id, "Переміщення створює конфлікт іншої задачі")
            QMessageBox.warning(self, "Переміщення скасовано", message)
            return
        self.store.save(task)
        self.replan()

    def unlock_task(self, task):
        task.locked_segments = []
        self.store.save(task)
        self.replan()

    def correct_power(self):
        dialog = OutageDialog(self.now(), self)
        if dialog.exec():
            self.apply_power_change(dialog.change)

    def apply_power_change(self, change):
        now = self.now()
        self.store.set("overrides", [*self.store.get("overrides", []), change])
        if not change["power"] and datetime.fromisoformat(
            change["start"]
        ) <= now < datetime.fromisoformat(change["end"]):
            for task in self.store.tasks():
                if task.status == "running":
                    self.task_action(task, "paused")
        self.refresh_overrides()
        self.replan()
        if (
            self.store.get("notifications", True)
            and change["power"]
            and datetime.fromisoformat(change["start"])
            <= now
            < datetime.fromisoformat(change["end"])
        ):
            self.deliver_notice(
                Notice(
                    "confirmed_power",
                    datetime.fromisoformat(change["start"]),
                    "Світло з’явилося",
                    "Стан підтверджено вами. Оновлюю розклад найближчих задач.",
                )
            )

    def refresh_overrides(self):
        self.override_list.clear()
        for change in self.store.get("overrides", []):
            begin = datetime.fromisoformat(change["start"]).astimezone(self.now().tzinfo)
            end = datetime.fromisoformat(change["end"]).astimezone(self.now().tzinfo)
            self.override_list.addItem(
                f"{begin:%d.%m %H:%M} — {end:%d.%m %H:%M}: "
                + ("є світло" if change["power"] else "немає світла")
            )

    def delete_override(self):
        index = self.override_list.currentRow()
        if index >= 0:
            changes = self.store.get("overrides", [])
            changes.pop(index)
            self.store.set("overrides", changes)
            self.refresh_overrides()
            self.replan()

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def exit_app(self):
        self.allow_exit = True
        self.close()

    def closeEvent(self, event):
        if not self.allow_exit and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self.timer.stop()
            self.notifier.shutdown()
            self.tray.hide()
            event.accept()

    def record_progress(self, task, until):
        device = next((d for d in self.store.devices() if d.id == task.device_id), None)
        if not device or not task.started_at:
            return
        battery = BatteryProfile(**self.store.get("battery", {}))
        elapsed, energy = progress_since_start(
            task,
            device,
            self.store.get("week", blank_week()),
            self.store.get("overrides", []),
            until,
            battery,
        )
        task.completed = min(task.minutes, task.completed + elapsed)
        task.started_at = None
        if energy:
            battery.charge = max(0, battery.charge - energy / battery.capacity_wh * 100)
            self.store.set("battery", asdict(battery))
            self.reserve_panel.charge.setValue(battery.charge)
        if task.target is not None:
            device.charge = max(
                0,
                min(
                    task.target,
                    task.target
                    - task.remaining
                    * device.power
                    * device.efficiency
                    / (60 * device.capacity)
                    * 100,
                ),
            )
            self.store.save(device)
            self.refresh_devices()

    def save_week(self):
        try:
            validate_week(self.editor.week)
        except ValueError as error:
            QMessageBox.warning(self, "Перевірте графік", str(error))
            return
        self.store.set("week", self.editor.week)
        self.replan()
        self.tabs.setCurrentIndex(0)

    def save_settings(self):
        if self.background.value() > self.power.value():
            QMessageBox.warning(self, "Перевірте потужність", "Фонове споживання перевищує ліміт")
            return
        try:
            if self.autostart_checkbox.isChecked() != self.autostart.enabled():
                self.autostart.set_enabled(self.autostart_checkbox.isChecked())
        except OSError as error:
            QMessageBox.warning(self, "Автозапуск не змінено", str(error))
            return
        self.store.set("power_limit", self.power.value())
        self.store.set("background_power", self.background.value())
        self.store.set("notifications", self.notifications.isChecked())
        self.store.set("algorithm", "dp" if self.algorithm.currentIndex() else "greedy")
        self.replan()

    def add_device(self):
        dialog = DeviceDialog(self)
        if dialog.exec():
            self.store.save(dialog.result_device)
            self.refresh_devices()
            self.replan()

    def edit_device(self, *args):
        row = self.device_list.currentRow()
        devices = self.store.devices()
        if row < 0:
            return
        dialog = DeviceDialog(self, devices[row])
        if dialog.exec():
            self.store.save(dialog.result_device)
            self.refresh_devices()
            self.replan()

    def refresh_devices(self):
        self.device_list.clear()
        for device in self.store.devices():
            detail = (
                f"{device.capacity:g} Вт·год · заряд {device.charge:g} %"
                if device.kind == "battery"
                else f"цикл {device.duration} хв"
            )
            self.device_list.addItem(
                f"{device.name}    {device.power:g} Вт    {detail}    пріоритет {device.priority}"
            )
        if hasattr(self, "reserve_panel"):
            self.reserve_panel.reload_devices()

    def add_task(self):
        devices = self.store.devices()
        if not devices:
            self.add_device()
            devices = self.store.devices()
        if not devices:
            return
        dialog = TaskDialog(devices, self.now(), self)
        if dialog.exec():
            self.store.save(dialog.result_task)
            self.replan()
            self.tabs.setCurrentIndex(0)

    def replan(self):
        self.revision += 1
        worker = PlanWorker(
            self.revision,
            self.planning_arguments(),
        )
        worker.signals.ready.connect(self.plan_ready)
        worker.signals.failed.connect(self.plan_failed)
        self.workers[self.revision] = worker
        self.status.setText("Розраховую розклад…")
        QThreadPool.globalInstance().start(worker)

    def plan_ready(self, revision, plan):
        self.workers.pop(revision, None)
        if revision != self.revision:
            return
        self.plan = plan
        self.render()
        self.process_notices()

    def plan_failed(self, revision, message):
        self.workers.pop(revision, None)
        if revision == self.revision:
            self.status.setText("Не вдалося розрахувати розклад: " + message)

    def render(self):
        now = self.now()
        week = self.store.get("week", blank_week())
        power = power_at(week, now, self.store.get("overrides", []))
        actual = any(
            datetime.fromisoformat(change["start"]) <= now < datetime.fromisoformat(change["end"])
            for change in self.store.get("overrides", [])
        )
        self.status.setText(
            f"{now:%d.%m.%Y · %H:%M}  |  "
            + ("За вашим уточненням: " if actual else "За графіком: ")
            + (
                "є світло"
                if power is True
                else "немає світла"
                if power is False
                else "стан не задано"
            )
            + f"  |  Конфліктів: {len(self.plan.conflicts)}"
        )
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tasks = self.store.tasks()
        active = [task for task in tasks if task.status not in {"done", "cancelled"}]
        self.task_count.setText(f"Активних: {len(active)} · Усього: {len(tasks)}")
        self.metric_labels[0][0].setText(
            "Є світло" if power is True else "Без світла" if power is False else "Немає даних"
        )
        self.metric_labels[0][1].setText(
            "Підтверджено вами" if actual else "За графіком електропостачання"
        )
        self.metric_labels[1][0].setText(f"{len(active)} активних")
        self.metric_labels[1][1].setText(
            f"{len(self.plan.conflicts)} потребують уваги"
            if self.plan.conflicts
            else "Усе готово до вашого дня"
        )
        self.timeline.plan = self.plan
        self.timeline.tasks = active
        self.timeline.week = week
        self.timeline.overrides = self.store.get("overrides", [])
        self.timeline.now = now
        self.timeline.setMinimumHeight(max(140, 85 + 36 * len(active)))
        self.timeline_panel.setMinimumHeight(max(140, 85 + 36 * min(len(active), 4)) + 68)
        self.timeline.update()
        profile = self.planning_arguments()["battery"]
        self.metric_labels[2][0].setText(
            f"{profile.usable_wh:.0f} Вт·год" if profile.enabled else "Не підключено"
        )
        self.metric_labels[2][1].setText(
            f"Заряд {profile.charge:.0f}% · мінімум {profile.reserve:.0f}%"
            if profile.enabled
            else "Налаштуйте на вкладці «Автономність»"
        )
        self.reserve_panel.plan_result.setText(
            f"План використає резерв: {self.plan.reserve_used_wh:.1f} Вт·год. "
            f"Доступний залишок вище мінімуму: {max(0, profile.usable_wh - self.plan.reserve_used_wh):.1f} Вт·год."
            if profile.enabled
            else "Резервне живлення вимкнено"
        )
        if not tasks:
            self.cards.addWidget(QLabel("Додайте першу задачу — і тут з’явиться ваш план."))
        states = {
            "pending": "Заплановано",
            "running": "Виконується — за вашим підтвердженням",
            "paused": "Призупинено",
            "done": "Виконано",
            "cancelled": "Скасовано",
        }
        for task in reversed(tasks):
            card = QFrame()
            card.setProperty("task_id", task.id)
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(18, 15, 18, 15)
            layout.setSpacing(10)
            heading = QHBoxLayout()
            device = next((d for d in self.store.devices() if d.id == task.device_id), None)
            glyph = QLabel()
            glyph.setPixmap(
                icon(
                    "battery" if device and device.kind == "battery" else "devices", "#639274", 24
                ).pixmap(24, 24)
            )
            heading.addWidget(glyph)
            label = QLabel(task.name)
            label.setStyleSheet("font-weight: 650; font-size: 11pt; color: #254638")
            heading.addWidget(label, 1)
            badge = QLabel(
                "Конфлікт"
                if task.id in self.plan.conflicts
                else "У роботі"
                if task.status == "running"
                else states.get(task.status, task.status)
            )
            badge.setObjectName("badge")
            badge.setProperty(
                "state", "conflict" if task.id in self.plan.conflicts else task.status
            )
            heading.addWidget(badge)
            layout.addLayout(heading)
            info = states.get(task.status, task.status)
            segments = [s for s in self.plan.segments if s.task_id == task.id]
            if task.id in self.plan.conflicts:
                info = "Конфлікт: " + self.plan.conflicts[task.id]
            elif segments:
                info += " · " + ", ".join(
                    f"{s.start.astimezone(now.tzinfo):%d.%m %H:%M}–"
                    f"{s.end.astimezone(now.tzinfo):%H:%M}"
                    for s in segments
                )
            info += (
                f"\nПідтверджено: {task.completed}/{task.minutes} хв · "
                f"до {datetime.fromisoformat(task.deadline).astimezone(now.tzinfo):%d.%m %H:%M}"
                f" · пріоритет {task.priority}"
            )
            detail = QLabel(info)
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            layout.addWidget(detail)
            if task.completed:
                progress = QProgressBar()
                progress.setRange(0, task.minutes)
                progress.setValue(task.completed)
                progress.setTextVisible(False)
                layout.addWidget(progress)
            if task.status not in {"done", "cancelled"}:
                actions = QHBoxLayout()
                if task.status != "running":
                    button(
                        "Продовжити" if task.completed else "Почати",
                        lambda checked=False, t=task: self.task_action(t, "running"),
                        actions,
                    ).setObjectName("primary")
                else:
                    button(
                        "Пауза",
                        lambda checked=False, t=task: self.task_action(t, "paused"),
                        actions,
                    )
                button(
                    "Виконано", lambda checked=False, t=task: self.task_action(t, "done"), actions
                )
                button(
                    "На завтра",
                    lambda checked=False, t=task: self.task_action(t, "tomorrow"),
                    actions,
                )
                actions.addStretch()
                button(
                    "Скасувати",
                    lambda checked=False, t=task: self.task_action(t, "cancelled"),
                    actions,
                ).setObjectName("quiet")
                layout.addLayout(actions)
                if task.locked_segments:
                    button(
                        "Зняти ручне закріплення",
                        lambda checked=False, t=task: self.unlock_task(t),
                        layout,
                    )
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            card.ensurePolished()
            card.layout().activate()
            card.setMinimumHeight(card.sizeHint().height())
            self.cards.addWidget(card)

    def task_action(self, task, action):
        now = self.now()
        if action == "running":
            other = [
                t
                for t in self.store.tasks()
                if t.device_id == task.device_id and t.id != task.id and t.status == "running"
            ]
            if other:
                QMessageBox.warning(
                    self, "Пристрій зайнятий", "Спочатку призупиніть іншу задачу пристрою"
                )
                return
            candidate = copy.deepcopy(task)
            candidate.status = "running"
            tasks = [candidate if value.id == task.id else value for value in self.store.tasks()]
            candidate.locked_segments = []
            check = build_plan(**self.planning_arguments(tasks))
            if task.id in check.conflicts:
                QMessageBox.warning(self, "Зараз виконати неможливо", check.conflicts[task.id])
                return
        if task.started_at:
            self.record_progress(task, now)
        task.locked_segments = []
        if action == "paused" and not task.interruptible:
            reply = QMessageBox.question(
                self,
                "Непереривана задача",
                "Після переривання потрібен новий повний цикл?\n"
                "Так — почати цикл спочатку. Ні — зберегти залишок.",
            )
            if reply == QMessageBox.StandardButton.Yes:
                task.completed = 0
        if action == "tomorrow":
            deadline = datetime.fromisoformat(task.deadline).astimezone(now.tzinfo)
            deadline = deadline.replace(year=now.year, month=now.month, day=now.day) + timedelta(
                days=1
            )
            task.deadline = deadline.isoformat()
            task.status = "pending"
        else:
            task.status = action
        if action == "running":
            task.started_at = now.isoformat()
        elif action == "done":
            task.completed = task.minutes
            if task.target is not None:
                device = next(d for d in self.store.devices() if d.id == task.device_id)
                device.charge = task.target
                self.store.save(device)
                self.refresh_devices()
        self.store.save(task)
        self.replan()

    def tick(self):
        if self.allow_exit:
            return
        now = self.now()
        if now - self.last_tick > timedelta(minutes=2):
            # Час сну не зараховується як підтверджена робота пристроїв.
            for task in self.store.tasks():
                if task.status == "running" and task.started_at:
                    self.record_progress(task, self.last_tick)
                    task.status = "paused"
                    task.started_at = None
                    task.locked_segments = []
                    self.store.save(task)
            self.startup_notice = True
        self.last_tick = now
        if not self.workers:
            self.replan()

    def process_notices(self):
        now = self.now()
        previous = self.last_check
        self.last_check = now
        if not self.store.get("notifications", True):
            self.startup_notice = False
            return
        history = self.store.get("notification_history", {})
        notices = build_notices(
            self.store.get("week", blank_week()),
            self.store.get("overrides", []),
            self.plan,
            self.store.tasks(),
            self.store.devices(),
            now,
        )
        selected = due_notices(notices, now, previous, history)
        if self.startup_notice:
            self.startup_notice = False
            current = power_at(
                self.store.get("week", blank_week()), now, self.store.get("overrides", [])
            )
            summary = Notice(
                "summary",
                now.replace(second=0, microsecond=0),
                "Поточний план",
                (
                    "За актуальними даними: є світло. "
                    if current
                    else "За актуальними даними: немає світла. "
                    if current is False
                    else "Стан живлення не задано. "
                )
                + "План на 3 години: "
                + upcoming_text(self.plan, self.store.tasks(), now)
                + (f". Конфліктів: {len(self.plan.conflicts)}" if self.plan.conflicts else ""),
            )
            if summary.key not in history:
                self.deliver_notice(summary)
            # Історичні події не відтворюємо при запуску чи відновленні.
            selected = [notice for notice in selected if notice.kind == "conflict"]
        for notice in selected:
            self.deliver_notice(notice)

    def deliver_notice(self, notice):
        history = self.store.get("notification_history", {})
        if notice.key in history:
            return
        history[notice.key] = self.now().isoformat()
        self.store.set("notification_history", dict(list(history.items())[-5000:]))
        entries = self.store.get("notification_inbox", [])
        entries.append(
            {
                "title": notice.title,
                "body": notice.body,
                "kind": notice.kind,
                "task_id": notice.object_id.split(":")[0]
                if notice.kind in {"conflict", "finish"}
                else "",
                "time": self.now().isoformat(),
            }
        )
        self.store.set("notification_inbox", entries[-200:])
        self.refresh_inbox()
        self.notifier.send(notice)

    def refresh_inbox(self):
        previous = self.current_notice
        self.inbox.clear()
        entries = list(reversed(self.store.get("notification_inbox", [])))
        for entry in entries:
            self.inbox.addItem(
                f"{datetime.fromisoformat(entry['time']):%d.%m %H:%M} · {entry['title']}"
            )
        if entries:
            self.inbox.setCurrentRow(entries.index(previous) if previous in entries else 0)
        else:
            self.select_notice(-1)

    def select_notice(self, row):
        entries = list(reversed(self.store.get("notification_inbox", [])))
        self.current_notice = entries[row] if 0 <= row < len(entries) else None
        if self.current_notice:
            self.notice_detail.setText(self.current_notice["body"])
        task = next(
            (
                task
                for task in self.store.tasks()
                if self.current_notice and task.id == self.current_notice["task_id"]
            ),
            None,
        )
        self.notice_open.setEnabled(self.current_notice is not None)
        available = task is not None and task.status not in {"done", "cancelled"}
        self.notice_tomorrow.setEnabled(available)
        self.notice_done.setEnabled(available)

    def notice_action(self, action):
        if self.current_notice:
            self.handle_notice_action(self.current_notice["task_id"], action)

    def handle_notice_action(self, task_id, action):
        task = next((task for task in self.store.tasks() if task.id == task_id), None)
        if action in {"tomorrow", "done"} and task and task.status not in {"done", "cancelled"}:
            self.task_action(task, action)
        else:
            self.show_from_tray()
            self.tabs.setCurrentIndex(0)
            for index in range(self.cards.count()):
                widget = self.cards.itemAt(index).widget()
                if widget and widget.property("task_id") == task_id:
                    self.cards_scroll.ensureWidgetVisible(widget)
                    break

    def export_plan(self):
        if not self.plan:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Експорт плану", "plan.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        {
                            "segments": [
                                {
                                    "task_id": s.task_id,
                                    "start": s.start.isoformat(),
                                    "end": s.end.isoformat(),
                                }
                                for s in self.plan.segments
                            ],
                            "conflicts": self.plan.conflicts,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as error:
                QMessageBox.warning(self, "Експорт не виконано", str(error))

    def export_calendar(self):
        if not self.plan or self.workers:
            QMessageBox.information(
                self, "Розклад ще обчислюється", "Дочекайтеся завершення розрахунку"
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт календаря", "blackout-plan.ics", "iCalendar (*.ics)"
        )
        if path:
            try:
                Path(path).write_bytes(export_ics(self.plan, self.store.tasks(), self.now()))
            except OSError as error:
                QMessageBox.warning(self, "Експорт не виконано", str(error))

    def backup_data(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Резервна копія", "blackout-backup.sqlite3", "SQLite (*.sqlite3)"
        )
        if path:
            try:
                self.store.backup(Path(path))
                self.statusBar().showMessage("Резервну копію збережено", 5000)
            except (OSError, ValueError, sqlite3.Error) as error:
                QMessageBox.warning(self, "Копію не створено", str(error))

    def restore_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "Відновлення", "", "SQLite (*.sqlite3)")
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                "Відновити дані?",
                "Поточні дані буде замінено. Перед заміною автоматично збережеться страхова копія.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            safety = self.store.restore(Path(path))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Відновлення не виконано", str(error))
            return
        self.editor.week = self.store.get("week", blank_week())
        self.editor.render()
        self.power.setValue(self.store.get("power_limit", 3500))
        self.background.setValue(self.store.get("background_power", 0))
        self.notifications.setChecked(self.store.get("notifications", True))
        self.algorithm.setCurrentIndex(self.store.get("algorithm", "greedy") == "dp")
        for task in self.store.tasks():
            if task.status == "running":
                task.status = "paused"
                task.started_at = None
                self.store.save(task)
        profile = BatteryProfile(**self.store.get("battery", {}))
        panel = self.reserve_panel
        for widget, value in [
            (panel.capacity, profile.capacity_wh),
            (panel.charge, profile.charge),
            (panel.reserve, profile.reserve),
            (panel.output, profile.output_w),
            (panel.efficiency, profile.efficiency * 100),
        ]:
            widget.setValue(value)
        panel.enabled.setChecked(profile.enabled)
        panel.transfer.setChecked(profile.continuous_transfer)
        self.refresh_devices()
        self.refresh_overrides()
        self.refresh_inbox()
        self.replan()
        QMessageBox.information(self, "Дані відновлено", f"Страхова копія: {safety}")
