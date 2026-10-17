from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import autostart


class RegistryKey:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeRegistry:
    """Small in-memory registry; tests never call the real winreg API."""
    HKEY_CURRENT_USER = "current-user"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_BINARY = 3

    def __init__(self):
        self.values = {}
        self.failure = None

    def OpenKey(self, root, path, reserved=0, access=KEY_READ):
        assert root == self.HKEY_CURRENT_USER
        if self.failure:
            raise self.failure
        if path not in self.values:
            raise FileNotFoundError(path)
        return RegistryKey(path)

    def CreateKeyEx(self, root, path, reserved=0, access=KEY_SET_VALUE):
        assert root == self.HKEY_CURRENT_USER
        if self.failure:
            raise self.failure
        self.values.setdefault(path, {})
        return RegistryKey(path)

    def QueryValueEx(self, key, name):
        try:
            return self.values[key.path][name]
        except KeyError:
            raise FileNotFoundError(name)

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[key.path][name] = (value, value_type)

    def DeleteValue(self, key, name):
        try:
            del self.values[key.path][name]
        except KeyError:
            raise FileNotFoundError(name)


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.registry_patch = patch.object(autostart, "winreg", self.registry)
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        self.command = '"C:\\奶娃 小窝\\奶娃桌宠.exe"'
        self.command_patch = patch.object(autostart, "_startup_command", return_value=self.command)
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def put_command(self, command=None, value_type=None):
        self.registry.values[autostart.RUN_KEY] = {
            autostart.VALUE_NAME: (self.command if command is None else command,
                                  self.registry.REG_SZ if value_type is None else value_type),
            "OtherApplication": ("leave me alone", self.registry.REG_SZ),
        }

    def put_approval(self, state=3, value_type=None, data=None):
        self.registry.values[autostart.APPROVAL_KEY] = {
            autostart.VALUE_NAME: (state.to_bytes(4, "little") + bytes(8) if data is None else data,
                                  self.registry.REG_BINARY if value_type is None else value_type),
            "OtherApplication": (bytes([3]) + bytes(11), self.registry.REG_BINARY),
        }

    def test_missing_key_and_missing_value_are_disabled(self):
        self.assertFalse(autostart.is_enabled())
        self.registry.values[autostart.RUN_KEY] = {}
        self.assertFalse(autostart.is_enabled())

    def test_only_current_exact_command_is_enabled(self):
        for command in (self.command + " --panel", r"C:\Other\pet.exe", ""):
            with self.subTest(command=command):
                self.put_command(command)
                self.assertFalse(autostart.is_enabled())
        self.put_command(self.command.swapcase() + " ")
        self.assertTrue(autostart.is_enabled())

    def test_wrong_run_value_type_is_disabled(self):
        self.put_command(value_type=self.registry.REG_BINARY)
        self.assertFalse(autostart.is_enabled())

    def test_windows_disabled_and_unknown_approval_states_are_disabled(self):
        self.put_command()
        for state in (0, 3, 7, 19):
            with self.subTest(state=state):
                self.put_approval(state)
                self.assertFalse(autostart.is_enabled())

    def test_enabled_and_missing_approval_states_are_enabled(self):
        self.put_command()
        self.assertTrue(autostart.is_enabled())
        self.registry.values[autostart.APPROVAL_KEY] = {}
        self.assertTrue(autostart.is_enabled())
        for state in (2, 6):
            with self.subTest(state=state):
                self.put_approval(state)
                self.assertTrue(autostart.is_enabled())

    def test_malformed_approval_is_not_reported_enabled(self):
        self.put_command()
        for data, value_type in ((b"\x02", self.registry.REG_BINARY),
                                 ("enabled", self.registry.REG_SZ)):
            with self.subTest(data=data):
                self.put_approval(data=data, value_type=value_type)
                self.assertFalse(autostart.is_enabled())

    def test_enable_creates_our_value_and_removes_only_our_old_approval(self):
        self.put_command("old copy")
        self.put_approval(3)
        autostart.set_enabled(True)
        self.assertTrue(autostart.is_enabled())
        self.assertEqual(self.registry.values[autostart.RUN_KEY][autostart.VALUE_NAME],
                         (self.command, self.registry.REG_SZ))
        self.assertNotIn(autostart.VALUE_NAME, self.registry.values[autostart.APPROVAL_KEY])
        self.assertEqual(self.registry.values[autostart.RUN_KEY]["OtherApplication"][0], "leave me alone")
        self.assertIn("OtherApplication", self.registry.values[autostart.APPROVAL_KEY])

    def test_enable_without_existing_registry_keys(self):
        autostart.set_enabled(True)
        self.assertTrue(autostart.is_enabled())
        self.assertNotIn(autostart.APPROVAL_KEY, self.registry.values)

    def test_disable_removes_our_value_and_preserves_everything_else(self):
        self.put_command()
        self.put_approval(2)
        before_approval = self.registry.values[autostart.APPROVAL_KEY].copy()
        autostart.set_enabled(False)
        self.assertFalse(autostart.is_enabled())
        self.assertNotIn(autostart.VALUE_NAME, self.registry.values[autostart.RUN_KEY])
        self.assertIn("OtherApplication", self.registry.values[autostart.RUN_KEY])
        self.assertEqual(self.registry.values[autostart.APPROVAL_KEY], before_approval)
        autostart.set_enabled(False)  # Idempotent if the value was already removed.

    def test_disable_when_nothing_is_registered(self):
        autostart.set_enabled(False)
        self.assertEqual(self.registry.values, {})

    def test_registry_access_failures_are_reported_to_the_caller(self):
        self.registry.failure = PermissionError("denied")
        for operation in (autostart.is_enabled, lambda: autostart.set_enabled(True),
                          lambda: autostart.set_enabled(False)):
            with self.subTest(operation=operation), self.assertRaises(OSError):
                operation()

    def test_approval_cleanup_failure_is_reported(self):
        self.put_command()
        self.put_approval()
        with patch.object(self.registry, "DeleteValue", side_effect=PermissionError("denied")):
            with self.assertRaises(OSError):
                autostart.set_enabled(True)

    def test_platform_without_winreg_reports_os_error(self):
        with patch.object(autostart, "winreg", None):
            with self.assertRaises(OSError):
                autostart.is_enabled()
            with self.assertRaises(OSError):
                autostart.set_enabled(True)


class StartupCommandTest(unittest.TestCase):
    def test_frozen_executable_uses_no_panel_or_other_arguments(self):
        executable = Path("C:/奶娃 小窝/奶娃桌宠.exe").resolve()
        with patch.object(autostart.sys, "frozen", True, create=True), \
                patch.object(autostart.sys, "executable", str(executable)):
            self.assertEqual(autostart._startup_command(), subprocess.list2cmdline([str(executable)]))

    def test_source_uses_adjacent_pythonw_and_absolute_main(self):
        executable = Path("C:/Python 安装/python.exe").resolve()
        with patch.object(autostart.sys, "frozen", False, create=True), \
                patch.object(autostart.sys, "executable", str(executable)), \
                patch.object(autostart.Path, "is_file", return_value=True):
            expected = [str(executable.with_name("pythonw.exe")),
                        str(Path(autostart.__file__).resolve().with_name("main.py"))]
            self.assertEqual(autostart._startup_command(), subprocess.list2cmdline(expected))

    def test_source_falls_back_to_current_python_if_pythonw_missing(self):
        executable = Path("C:/Python 安装/python.exe").resolve()
        with patch.object(autostart.sys, "frozen", False, create=True), \
                patch.object(autostart.sys, "executable", str(executable)), \
                patch.object(autostart.Path, "is_file", return_value=False):
            expected = [str(executable), str(Path(autostart.__file__).resolve().with_name("main.py"))]
            self.assertEqual(autostart._startup_command(), subprocess.list2cmdline(expected))


if __name__ == "__main__":
    unittest.main()
