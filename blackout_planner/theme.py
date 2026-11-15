"""Світла тема та векторні піктограми інтерфейсу."""

from math import ceil

from PySide6.QtCore import QByteArray, QRect, QRectF, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from .appearance import stylesheet

STYLE = stylesheet()

PATHS = {
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "panel-close": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18m8-13-4 4 4 4"/>',
    "bolt": '<path d="m13 2-8 12h6l-1 8 9-13h-6l0-7Z"/>',
    "today": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v5m10-5v5M3 11h18m-13 5h1m5 0h1"/>',
    "devices": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    "battery": '<rect x="2" y="6" width="18" height="12" rx="3"/><path d="M23 10v4M6 10v4m4-4v4m4-4v4"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9m-9 13h6"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
}


def svg_source(name, color):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round">{PATHS[name]}</svg>'
    ).encode()


class VectorIconEngine(QIconEngine):
    """Малює SVG у потрібній фізичній роздільності, включно з дробовим DPI."""

    def __init__(self, source):
        super().__init__()
        self.source = source

    def clone(self):
        return VectorIconEngine(self.source)

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if mode == QIcon.Mode.Disabled:
            painter.setOpacity(0.45)
        QSvgRenderer(QByteArray(self.source)).render(painter, QRectF(rect))
        painter.restore()

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1)

    def scaledPixmap(self, size, mode, state, scale):
        pixmap = QPixmap(ceil(size.width() * scale), ceil(size.height() * scale))
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


def icon(name, color="#DEC3B4", size=22):
    return QIcon(VectorIconEngine(svg_source(name, color)))


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.renderer = QSvgRenderer(QByteArray(svg_source("bolt", "#F1B29E")), self)
        self.setFixedSize(36, 36)
        self.setAccessibleName("Логотип Blackout Planner")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.renderer.render(painter, QRectF(self.rect().adjusted(2, 2, -2, -2)))
