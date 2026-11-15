"""Теракотова палітра світлої й темної тем."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = dict(
    background="#F8F4EF",
    surface="#FFFDFA",
    ink="#3C302C",
    muted="#756055",
    accent="#A85039",
    on_accent="#FFFFFF",
    soft="#F3E5DC",
    border="#E8DCD3",
    sidebar="#35251F",
    side_ink="#F5EAE2",
    side_muted="#C4AEA0",
    side_active="#614033",
    side_active_ink="#FFD9C7",
    power="#E3EDE4",
    power_ink="#42694B",
    outage="#E8E2DD",
    outage_ink="#6E625B",
    warning="#FFF1DA",
    warning_ink="#805412",
    danger="#F7E5E1",
    danger_ink="#A23E37",
    grid="#EBE3DC",
    task="#B87861",
)
DARK = dict(
    background="#211A17",
    surface="#2D231E",
    ink="#F5EAE2",
    muted="#C4AEA0",
    accent="#F1B29E",
    on_accent="#3C2017",
    soft="#462F25",
    border="#4C3C32",
    sidebar="#191310",
    side_ink="#F5EAE2",
    side_muted="#C4AEA0",
    side_active="#4B3026",
    side_active_ink="#FFD9C7",
    power="#304334",
    power_ink="#B1D2B5",
    outage="#443B35",
    outage_ink="#C8B9AE",
    warning="#49391F",
    warning_ink="#F3CE87",
    danger="#482B27",
    danger_ink="#F2B4AC",
    grid="#44362E",
    task="#C58F78",
)

TEMPLATE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: @ink; }
QMainWindow, QDialog, QWizard, QWizardPage, QWizard > QWidget { background: @background; }
QFrame#sidebar { background: @sidebar; border: 0; }
QLabel#brand { color: @side_ink; font-size: 16pt; font-weight: 650; }
QLabel#brandSub { color: @side_muted; font-size: 9pt; }
QLabel#navCaption { color: @side_muted; font-size: 8pt; }
QPushButton#nav { color: @side_muted; background: transparent; border: 0;
 border-radius: 9px; text-align: left; padding: 13px 15px; }
QPushButton#nav:hover { background: @side_active; color: @side_ink; }
QPushButton#nav:checked { background: @side_active; color: @side_active_ink; font-weight: 600; }
QLabel#title { font-size: 23pt; font-weight: 650; color: @ink; }
QLabel#muted, QLabel#metricCaption, QLabel#metricHint { color: @muted; font-size: 9pt; }
QLabel#sectionTitle { font-size: 13pt; font-weight: 600; color: @ink; }
QLabel#cardTitle { font-size: 11pt; font-weight: 600; color: @ink; }
QFrame#card, QFrame#timelinePanel, QFrame#reserveSummary { background: @surface;
 border: 1px solid @border; border-radius: 13px; }
QFrame#dayLead { background: @soft; border: 0; border-radius: 14px; }
QLabel#leadTitle { font-size: 16pt; font-weight: 600; color: @ink; }
QLabel#reserveValue { font-size: 20pt; font-weight: 600; color: @ink; }
QLabel#badge { color: @muted; background: @background; border-radius: 6px;
 padding: 4px 9px; font-size: 8pt; font-weight: 500; }
QLabel#badge[state='conflict'] { color: @danger_ink; background: @danger; }
QLabel#badge[state='paused'] { color: @warning_ink; background: @warning; }
QLabel#badge[state='done'] { color: @power_ink; background: @power; }
QTabWidget::pane { border: 0; background: transparent; }
QPushButton { background: @surface; color: @ink; border: 1px solid @border;
 border-radius: 8px; padding: 9px 14px; font-weight: 500; }
QPushButton:hover { background: @soft; border-color: @accent; }
QPushButton:pressed { background: @soft; }
QPushButton:focus { border: 1px solid @accent; }
QPushButton#primary { background: @accent; color: @on_accent; border: 1px solid @accent; }
QPushButton#primary:hover { border: 1px solid @ink; }
QPushButton#quiet { background: transparent; color: @muted; border: 0; }
QPushButton#quiet:hover { background: @danger; color: @danger_ink; }
QPushButton:disabled { color: @muted; background: @background; border-color: @border; }
QLineEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QComboBox {
 background: @surface; border: 1px solid @border; border-radius: 7px; padding: 8px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus,
 QComboBox:focus { border-color: @accent; }
QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
 width: 20px; border: 0; background: transparent; }
QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
 width: 20px; border: 0; background: transparent; }
QComboBox::drop-down { border: 0; width: 25px; }
QListWidget, QTableWidget { background: @surface; border: 1px solid @border;
 border-radius: 10px; outline: 0; selection-background-color: @soft; selection-color: @ink; }
QListWidget::item { padding: 12px 10px; border-bottom: 1px solid @border; }
QListWidget::item:selected { background: @soft; border-radius: 6px; }
QHeaderView::section { background: @background; color: @muted; border: 0; padding: 9px; }
QTableWidget { gridline-color: @border; }
QCheckBox { spacing: 9px; padding: 5px 0; }
QCheckBox::indicator, QListWidget::indicator { width: 15px; height: 15px;
 border: 1px solid @border; border-radius: 4px; background: @surface; }
QCheckBox::indicator:checked, QListWidget::indicator:checked {
 background: @accent; border: 3px solid @soft; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 3px; }
QScrollBar::handle:vertical { background: @border; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { background: @background; border: 0; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: @accent; border-radius: 3px; }
QToolTip { background: @sidebar; color: @side_ink; border: 0; padding: 7px; }
QMenu { background: @surface; border: 1px solid @border; padding: 6px; }
QMenu::item { padding: 9px 20px; }
QMenu::item:selected { background: @soft; }
QStatusBar { color: @muted; background: @background; }
QPushButton#sidebarToggle { background: transparent; border: 1px solid @border;
 border-radius: 8px; padding: 7px; }
QPushButton#sidebarToggle:hover { background: @soft; border-color: @accent; }
"""


def colors():
    app = QApplication.instance()
    return DARK if app and app.property("appearance") == "dark" else LIGHT


def stylesheet(mode="light"):
    result = TEMPLATE
    for name, value in sorted(
        (DARK if mode == "dark" else LIGHT).items(), key=lambda pair: -len(pair[0])
    ):
        result = result.replace("@" + name, value)
    return result


def apply_theme(app, mode):
    mode = "dark" if mode == "dark" else "light"
    app.setProperty("appearance", mode)
    values = DARK if mode == "dark" else LIGHT
    palette = QPalette()
    for role, name in [
        (QPalette.ColorRole.Window, "background"),
        (QPalette.ColorRole.WindowText, "ink"),
        (QPalette.ColorRole.Base, "surface"),
        (QPalette.ColorRole.AlternateBase, "background"),
        (QPalette.ColorRole.Text, "ink"),
        (QPalette.ColorRole.Button, "surface"),
        (QPalette.ColorRole.ButtonText, "ink"),
        (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.HighlightedText, "on_accent"),
    ]:
        palette.setColor(role, QColor(values[name]))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(mode))
    for widget in app.allWidgets():
        widget.update()
