"""Розміри вікон у логічних пікселях доступної робочої області."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFormLayout, QScrollArea, QVBoxLayout, QWidget


def fit_window(window, preferred=(1180, 800), minimum=(560, 420), bounds=None):
    screen = QApplication.screenAt(QCursor.pos()) or window.screen()
    bounds = bounds or screen.availableGeometry()
    width = min(preferred[0], max(1, int(bounds.width() * 0.92)))
    height = min(preferred[1], max(1, int(bounds.height() * 0.88)))
    window.setMinimumSize(min(minimum[0], width), min(minimum[1], height))
    window.resize(width, height)
    window.move(
        bounds.x() + (bounds.width() - width) // 2, bounds.y() + (bounds.height() - height) // 2
    )


def scroll_page(widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    return scroll


def dialog_form(dialog):
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(6, 6, 6, 6)
    body = QWidget()
    form = QFormLayout(body)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    outer.addWidget(scroll_page(body))
    return form
