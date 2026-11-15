"""Світла тема та векторні піктограми інтерфейсу."""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #243b38; }
QMainWindow, QDialog, QWizard, QWizardPage, QWizard > QWidget { background: #f4f7f6; }
QFrame#sidebar { background: #122f2b; border: 0; }
QLabel#brand { color: #ffffff; font-size: 16pt; font-weight: 700; }
QLabel#brandSub { color: #8faea5; font-size: 9pt; }
QLabel#navCaption { color: #7f9f96; font-size: 8pt; font-weight: 600; }
QPushButton#nav { color: #b7ccc5; background: transparent; border: 0;
 border-radius: 9px; text-align: left; padding: 13px 15px; font-size: 10pt; }
QPushButton#nav:hover { background: #1c4038; color: #ffffff; }
QPushButton#nav:checked { background: #265345; color: #d6faab; font-weight: 600; }
QLabel#title { font-size: 24pt; font-weight: 700; color: #173a32; }
QLabel#muted { color: #61796c; font-size: 9pt; }
QLabel#sectionTitle { font-size: 13pt; font-weight: 650; color: #24453b; }
QFrame#metric, QFrame#card, QFrame#timelinePanel { background: #ffffff;
 border: 1px solid #e2eae6; border-radius: 13px; }
QLabel#metricCaption { color: #62776d; font-size: 9pt; }
QLabel#metricValue { color: #214737; font-size: 19pt; font-weight: 700; }
QLabel#metricHint { color: #84958d; font-size: 8pt; }
QLabel#badge { color: #387354; background: #ebf5eb; border-radius: 6px;
 padding: 4px 9px; font-size: 8pt; font-weight: 600; }
QLabel#badge[state='conflict'] { color: #a65b37; background: #fff0e5; }
QLabel#badge[state='paused'] { color: #92722d; background: #fbf3dc; }
QLabel#badge[state='done'] { color: #447a64; background: #ecf5f0; }
QTabWidget::pane { border: 0; background: transparent; }
QPushButton { background: #ffffff; color: #3e5d50; border: 1px solid #dae6df;
 border-radius: 8px; padding: 9px 14px; font-weight: 500; }
QPushButton:hover { background: #ecf4ee; border-color: #b7cfbf; }
QPushButton:pressed { background: #dcebdd; }
QPushButton:focus { border: 1px solid #74a788; }
QPushButton#primary { background: #275f46; color: #ffffff; border: 1px solid #275f46; }
QPushButton#primary:hover { background: #347c59; }
QPushButton#quiet { background: transparent; color: #81968b; border: 0; }
QPushButton#quiet:hover { background: #fff0eb; color: #ab624c; }
QPushButton:disabled { color: #a5b4ac; background: #f0f4f1; border-color: #e5ece7; }
QLineEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QComboBox {
 background: #ffffff; border: 1px solid #dce6df; border-radius: 7px; padding: 8px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus,
 QComboBox:focus { border-color: #6d9e7b; }
QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
 width: 20px; border: 0; background: transparent; }
QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
 width: 20px; border: 0; background: transparent; }
QComboBox::drop-down { border: 0; width: 25px; }
QListWidget, QTableWidget { background: #ffffff; border: 1px solid #e0e8e2;
 border-radius: 10px; outline: 0; selection-background-color: #e8f2e6;
 selection-color: #214737; }
QListWidget::item { padding: 12px 10px; border-bottom: 1px solid #f0f4f1; }
QListWidget::item:selected { background: #e8f2e6; border-radius: 6px; }
QHeaderView::section { background: #f0f5f0; color: #70877a; border: 0; padding: 9px; }
QTableWidget { gridline-color: #e4ece6; }
QCheckBox { spacing: 9px; padding: 5px 0; }
QCheckBox::indicator, QListWidget::indicator { width: 15px; height: 15px;
 border: 1px solid #b9cfc0; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:checked, QListWidget::indicator:checked { background: #36815b;
 border: 3px solid #bedbc5; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 3px; }
QScrollBar::handle:vertical { background: #c8d8cc; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { background: #edf3ed; border: 0; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #84b578; border-radius: 3px; }
QToolTip { background: #193e30; color: #ffffff; border: 0; padding: 7px; }
QMenu { background: #ffffff; border: 1px solid #dce6df; padding: 6px; }
QMenu::item { padding: 9px 20px; }
QMenu::item:selected { background: #e8f2e6; }
QStatusBar { color: #82988a; background: #f4f7f6; }
"""

PATHS = {
    "bolt": '<path d="m13 2-8 12h6l-1 8 9-13h-6l0-7Z"/>',
    "today": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v5m10-5v5M3 11h18m-13 5h1m5 0h1"/>',
    "devices": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    "battery": '<rect x="2" y="6" width="18" height="12" rx="3"/><path d="M23 10v4M6 10v4m4-4v4m4-4v4"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9m-9 13h6"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
}


def icon(name, color="#a8c7b7", size=22):
    source = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round">{PATHS[name]}</svg>'
    )
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(source.encode())).render(painter)
    painter.end()
    return QIcon(pixmap)
