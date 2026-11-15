"""Один процес на каталог даних і відкриття вже запущеного вікна."""

import hashlib
import os

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, folder):
        super().__init__()
        folder.mkdir(parents=True, exist_ok=True)
        self.name = (
            "BlackoutPlanner-"
            + hashlib.sha256(os.path.normcase(str(folder.resolve())).encode()).hexdigest()[:24]
        )
        self.lock = QLockFile(str(folder / "process.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.accept)

    def acquire(self, activate=True):
        if not self.lock.tryLock(0):
            if activate:
                socket = QLocalSocket()
                socket.connectToServer(self.name)
                if socket.waitForConnected(500):
                    socket.waitForReadyRead(1000)
                    socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise OSError("Не вдалося створити локальний канал застосунку")
        return True

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.activated.emit()
            socket.write(b"ok")
            socket.flush()
            socket.waitForBytesWritten(200)
            socket.disconnectFromServer()
            socket.deleteLater()

    def release(self):
        self.server.close()
        self.lock.unlock()
