"""Open the pet's ChatGPT shortcut in the user's installed Google Chrome."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterator

try:
    import winreg
except ImportError:  # Allows development and unit tests outside Windows.
    winreg = None


CHATGPT_URL = "https://chatgpt.com/"
_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"


def _registry_candidates() -> Iterator[str]:
    if winreg is None:
        return
    # An installation registered for this user takes precedence over a system one.
    views = (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                with winreg.OpenKey(hive, _APP_PATH, 0, winreg.KEY_READ | view) as key:
                    value, value_type = winreg.QueryValueEx(key, None)
                if isinstance(value, str) and value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    yield value
            except OSError:
                continue


def _executable(candidate: str | Path) -> Path | None:
    value = str(candidate).strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    path = Path(os.path.expandvars(value))
    try:
        if path.name.lower() == "chrome.exe" and path.is_file():
            return path.resolve()
    except OSError:
        pass
    return None


def find_chrome() -> Path:
    """Locate an actual Chrome executable without opening browser profile data."""
    for candidate in _registry_candidates():
        if executable := _executable(candidate):
            return executable
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if root := os.environ.get(variable):
            if executable := _executable(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"):
                return executable
    if candidate := shutil.which("chrome.exe"):
        if executable := _executable(candidate):
            return executable
    raise FileNotFoundError("没有找到谷歌 Chrome，请安装后使用小窝里的“打开 ChatGPT”。")


def open_chatgpt() -> None:
    """Start Chrome asynchronously; an existing Chrome session handles the new tab."""
    subprocess.Popen([str(find_chrome()), "--new-tab", CHATGPT_URL], shell=False)
