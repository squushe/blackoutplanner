"""Автозапуск для поточного користувача Windows та Linux."""

import os
import subprocess
import sys
from pathlib import Path

NAME = "BlackoutPlanner"


def launch_arguments(data_dir, executable=None, frozen=None):
    executable = Path(executable or sys.executable)
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if sys.platform == "win32" and executable.name.lower() == "python.exe":
        windowless = executable.with_name("pythonw.exe")
        if windowless.exists():
            executable = windowless
    command = [str(executable)]
    if not frozen:
        # Абсолютний launcher працює незалежно від поточного каталогу ОС.
        command += [str(Path(__file__).resolve().with_name("launcher.py"))]
    return command + ["--data-dir", str(Path(data_dir).resolve()), "--background"]


def desktop_exec(arguments):
    """Desktop Entry Exec: без shell, з екрануванням зарезервованих символів."""
    return " ".join(
        '"'
        + value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
        + '"'
        for value in arguments
    )


class Autostart:
    def __init__(self, data_dir, platform=None, config_dir=None):
        self.last_error = None
        self.arguments = launch_arguments(data_dir)
        self.platform = platform or sys.platform
        self.desktop_path = (
            Path(config_dir or os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "autostart"
            / "blackout-planner.desktop"
        )

    def enabled(self):
        self.last_error = None
        if self.platform == "win32":
            import winreg

            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
                ) as key:
                    value, _ = winreg.QueryValueEx(key, NAME)
                    return value == subprocess.list2cmdline(self.arguments)
            except FileNotFoundError:
                return False
            except OSError as error:
                self.last_error = str(error)
                return False
        if self.platform.startswith("linux"):
            try:
                return self.desktop_path.exists() and "Hidden=true" not in self.desktop_path.read_text(
                    encoding="utf-8"
                )
            except OSError as error:
                self.last_error = str(error)
                return False
        return False

    def set_enabled(self, enabled):
        if self.platform == "win32":
            import winreg

            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key, NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(self.arguments)
                    )
                else:
                    try:
                        winreg.DeleteValue(key, NAME)
                    except FileNotFoundError:
                        pass
        elif self.platform.startswith("linux"):
            if enabled:
                self.desktop_path.parent.mkdir(parents=True, exist_ok=True)
                self.desktop_path.write_text(
                    "[Desktop Entry]\nType=Application\nName=Blackout Planner\n"
                    "Exec="
                    + desktop_exec(self.arguments)
                    + "\nTerminal=false\nX-GNOME-Autostart-enabled=true\n",
                    encoding="utf-8",
                )
            else:
                self.desktop_path.unlink(missing_ok=True)
        else:
            raise OSError("Автозапуск підтримується у Windows та Linux")
