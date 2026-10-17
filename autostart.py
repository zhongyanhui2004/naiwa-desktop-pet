"""Current-user Windows sign-in startup for this copy of Naiwa Desktop Pet."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

try:
    import winreg
except ImportError:  # Keep the source importable for tests on other platforms.
    winreg = None


VALUE_NAME = "NaiwaDesktopPet"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVAL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def _startup_command() -> str:
    """Build the same safely quoted command for both reading and writing."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        arguments = [str(executable)]
    else:
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            executable = windowless
        arguments = [str(executable), str(Path(__file__).resolve().with_name("main.py"))]
    return subprocess.list2cmdline(arguments)


def _registry():
    if winreg is None:
        raise OSError("开机自启动仅支持 Windows。")
    return winreg


def is_enabled() -> bool:
    """Whether Windows will start this exact installation at the user's sign-in.

    Missing entries mean disabled. Registry access errors are deliberately left
    to the caller so the panel can show the actual problem instead of a false
    success. StartupApproved is maintained by Windows' Startup Apps controls.
    A missing approval is allowed; existing disabled or unknown states are not.
    """
    registry = _registry()
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_READ) as key:
            command, value_type = registry.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    if (value_type != registry.REG_SZ or not isinstance(command, str)
            or command.strip().casefold() != _startup_command().casefold()):
        return False

    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, APPROVAL_KEY, 0, registry.KEY_READ) as key:
            approval, value_type = registry.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return True
    if value_type != registry.REG_BINARY or not isinstance(approval, bytes) or len(approval) < 4:
        return False
    # Windows uses 2 and 6 for enabled records and 3 and 7 for disabled
    # records. Treat future/unrecognized states as unavailable, not enabled.
    return int.from_bytes(approval[:4], "little") in (2, 6)


def set_enabled(enabled: bool) -> None:
    """Enable/disable only this app's HKCU Run value, without elevation.

    Enabling clears only our StartupApproved record rather than inventing a
    timestamp or writing an undocumented binary value. Windows then evaluates
    the newly registered app normally. Disabling removes our Run value and
    does not change any other app or Windows' approval records.
    """
    registry = _registry()
    if enabled:
        with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
            registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_SZ, _startup_command())
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, APPROVAL_KEY, 0, registry.KEY_SET_VALUE) as key:
                registry.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
    else:
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                registry.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
