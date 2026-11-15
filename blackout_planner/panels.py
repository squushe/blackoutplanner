"""Редактори датованого живлення та резервного джерела."""

from dataclasses import asdict
from datetime import timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .domain import BatteryProfile


def value_box(value, maximum, suffix):
    box = QDoubleSpinBox()
    box.setRange(0, maximum)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


class OutageDialog(QDialog):
    def __init__(self, now, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Уточнення електропостачання")
        self.zone = now.tzinfo
        self.change = None
        form = QFormLayout(self)
        self.power = QComboBox()
        self.power.addItems(["Світло зникло", "Світло з’явилося"])
        self.begin = QDateTimeEdit(now.replace(tzinfo=None, second=0, microsecond=0))
        self.end = QDateTimeEdit(
            (now + timedelta(hours=2)).replace(tzinfo=None, second=0, microsecond=0)
        )
        for edit in (self.begin, self.end):
            edit.setDisplayFormat("dd.MM.yyyy HH:mm")
            edit.setCalendarPopup(True)
        form.addRow("Фактичний стан", self.power)
        form.addRow("Від", self.begin)
        form.addRow("Діє до", self.end)
        note = QLabel(
            "Уточнення діє лише в цьому інтервалі. Потім знову використовується "
            "тижневий графік. Пізніше уточнення замінює попереднє на спільному проміжку."
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Застосувати")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(500, 280)

    def save(self):
        begin = self.begin.dateTime().toPython().replace(tzinfo=self.zone)
        end = self.end.dateTime().toPython().replace(tzinfo=self.zone)
        if end <= begin:
            QMessageBox.warning(self, "Перевірте час", "Кінець має бути пізніше початку")
            return
        self.change = {
            "start": begin.isoformat(),
            "end": end.isoformat(),
            "power": bool(self.power.currentIndex()),
        }
        self.accept()


class ReservePanel(QWidget):
    saved = Signal()

    def __init__(self, store):
        super().__init__()
        self.store = store
        profile = BatteryProfile(**store.get("battery", {}))
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Використовувати резервне джерело під час відключень")
        self.enabled.setChecked(profile.enabled)
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.capacity = value_box(profile.capacity_wh, 1000000, " Вт·год")
        self.charge = value_box(profile.charge, 100, " %")
        self.reserve = value_box(profile.reserve, 100, " %")
        self.output = value_box(profile.output_w, 100000, " Вт")
        self.efficiency = value_box(profile.efficiency * 100, 100, " %")
        self.transfer = QCheckBox("Обладнання забезпечує безперервний перехід мережа ↔ резерв")
        self.transfer.setChecked(profile.continuous_transfer)
        for title, widget in [
            ("Ємність", self.capacity),
            ("Поточний заряд", self.charge),
            ("Не розряджати нижче", self.reserve),
            ("Вихідна потужність", self.output),
            ("Ефективність розряджання", self.efficiency),
        ]:
            form.addRow(title, widget)
            widget.valueChanged.connect(self.calculate)
        layout.addLayout(form)
        layout.addWidget(self.transfer)
        columns = QHBoxLayout()
        self.compatible = QListWidget()
        self.simulation = QListWidget()
        for title, widget in [
            ("Дозволені навантаження резерву", self.compatible),
            ("Сценарій автономності — увімкнені пристрої", self.simulation),
        ]:
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            column.addWidget(widget)
            columns.addLayout(column)
        layout.addLayout(columns)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.plan_result = QLabel()
        layout.addWidget(self.result)
        layout.addWidget(self.plan_result)
        note = QLabel(
            "Оцінка для сталого навантаження. Майбутнє підзаряджання резерву "
            "не припускається. Сценарій праворуч не змінює задачі чи фактичний заряд."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        save = QPushButton("Зберегти резерв і перепланувати")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.simulation.itemChanged.connect(self.calculate)
        self.compatible.itemChanged.connect(self.calculate)
        self.reload_devices()

    def reload_devices(self):
        profile = BatteryProfile(**self.store.get("battery", {}))
        selected = {
            self.simulation.item(k).data(Qt.ItemDataRole.UserRole)
            for k in range(self.simulation.count())
            if self.simulation.item(k).checkState() == Qt.CheckState.Checked
        }
        self.simulation.blockSignals(True)
        self.compatible.clear()
        self.simulation.clear()
        for device in self.store.devices():
            for widget, checked in [
                (self.compatible, device.id in profile.compatible_ids),
                (self.simulation, device.id in selected),
            ]:
                item = QListWidgetItem(f"{device.name} · {device.power:g} Вт")
                item.setData(Qt.ItemDataRole.UserRole, device.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                widget.addItem(item)
        self.simulation.blockSignals(False)
        self.calculate()

    def profile(self):
        return BatteryProfile(
            self.capacity.value(),
            self.charge.value(),
            self.reserve.value(),
            self.output.value(),
            self.efficiency.value() / 100,
            [
                self.compatible.item(k).data(Qt.ItemDataRole.UserRole)
                for k in range(self.compatible.count())
                if self.compatible.item(k).checkState() == Qt.CheckState.Checked
            ],
            self.transfer.isChecked(),
            self.enabled.isChecked(),
        )

    def calculate(self, *args):
        if not hasattr(self, "result"):
            return
        selected = {
            self.simulation.item(k).data(Qt.ItemDataRole.UserRole)
            for k in range(self.simulation.count())
            if self.simulation.item(k).checkState() == Qt.CheckState.Checked
        }
        power = sum(device.power for device in self.store.devices() if device.id in selected)
        try:
            profile = self.profile()
            hours = profile.autonomy_hours(power)
            if selected - set(profile.compatible_ids):
                message = (
                    "Є недозволені навантаження: позначте їх сумісними або вимкніть у сценарії"
                )
            elif power > profile.output_w:
                message = "Перевищено вихідну потужність резерву"
            elif hours is None:
                message = "Немає активного споживання"
            else:
                message = f"Орієнтовна автономність: {int(hours * 60) // 60} год {int(hours * 60) % 60} хв"
            self.result.setText(f"Навантаження: {power:g} Вт. {message}")
        except ValueError as error:
            self.result.setText(str(error))

    def save(self):
        try:
            profile = self.profile()
            profile.validate()
        except ValueError as error:
            QMessageBox.warning(self, "Перевірте резерв", str(error))
            return
        self.store.set("battery", asdict(profile))
        self.saved.emit()
