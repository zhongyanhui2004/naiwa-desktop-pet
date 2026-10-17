from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import browser_launch


class BrowserLaunchTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="奶娃 Chrome 测试 ")
        self.root = Path(self.folder.name)
        self.registry = patch.object(browser_launch, "_registry_candidates", return_value=iter(()))
        self.registry.start()
        self.addCleanup(self.registry.stop)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.which = patch.object(browser_launch.shutil, "which", return_value=None)
        self.mock_which = self.which.start()
        self.addCleanup(self.which.stop)
        self.addCleanup(self.folder.cleanup)

    def chrome(self, parent: str) -> Path:
        executable = self.root / parent / "Google" / "Chrome" / "Application" / "chrome.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
        return executable.resolve()

    def test_registry_path_is_preferred_over_standard_installation(self):
        registered = self.chrome("registered")
        self.chrome("system")
        os.environ["ProgramFiles"] = str(self.root / "system")
        with patch.object(browser_launch, "_registry_candidates", return_value=iter((f'"{registered}"',))):
            self.assertEqual(browser_launch.find_chrome(), registered)
        self.mock_which.assert_not_called()

    def test_all_standard_installation_locations_are_supported(self):
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            with self.subTest(variable=variable), patch.dict(os.environ, {}, clear=True):
                executable = self.chrome(variable)
                os.environ[variable] = str(self.root / variable)
                self.assertEqual(browser_launch.find_chrome(), executable)

    def test_invalid_registry_files_are_skipped(self):
        directory = self.root / "chrome.exe"
        directory.mkdir()
        other = self.root / "not-chrome.exe"
        other.touch()
        executable = self.chrome("fallback")
        self.mock_which.return_value = str(executable)
        candidates = (self.root / "missing" / "chrome.exe", directory, other)
        with patch.object(browser_launch, "_registry_candidates", return_value=iter(candidates)):
            self.assertEqual(browser_launch.find_chrome(), executable)
        self.mock_which.assert_called_once_with("chrome.exe")

    def test_non_executable_path_lookup_is_rejected(self):
        script = self.root / "chrome.cmd"
        script.touch()
        self.mock_which.return_value = str(script)
        with self.assertRaises(FileNotFoundError):
            browser_launch.find_chrome()

    def test_missing_chrome_reports_a_useful_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "Chrome"):
            browser_launch.find_chrome()

    def test_launch_uses_separate_arguments_without_a_shell_or_wait(self):
        executable = self.chrome("中文 空格 & 浏览器")
        with patch.object(browser_launch, "find_chrome", return_value=executable), \
                patch.object(browser_launch.subprocess, "Popen") as launch:
            self.assertIsNone(browser_launch.open_chatgpt())
        launch.assert_called_once_with(
            [str(executable), "--new-tab", "https://chatgpt.com/"], shell=False
        )
        launch.return_value.wait.assert_not_called()
        launch.return_value.communicate.assert_not_called()

    def test_launch_failure_is_returned_to_the_ui(self):
        executable = self.chrome("failed")
        error = OSError("Access denied")
        with patch.object(browser_launch, "find_chrome", return_value=executable), \
                patch.object(browser_launch.subprocess, "Popen", side_effect=error):
            with self.assertRaises(OSError) as caught:
                browser_launch.open_chatgpt()
        self.assertIs(caught.exception, error)


class RegistryLookupTest(unittest.TestCase):
    def test_user_hive_precedes_machine_hive_and_expanded_values_are_accepted(self):
        registry = MagicMock()
        registry.HKEY_CURRENT_USER = "user"
        registry.HKEY_LOCAL_MACHINE = "machine"
        registry.KEY_READ = 1
        registry.KEY_WOW64_64KEY = 2
        registry.KEY_WOW64_32KEY = 4
        registry.REG_SZ = 1
        registry.REG_EXPAND_SZ = 2
        queries = []

        def open_key(hive, path, reserved, flags):
            queries.append((hive, path, reserved, flags))
            key = MagicMock()
            key.__enter__.return_value = (hive, flags)
            return key

        def read_value(key, name):
            self.assertIsNone(name)
            return ("user-path", 2) if key[0] == "user" else ("machine-path", 1)

        registry.OpenKey.side_effect = open_key
        registry.QueryValueEx.side_effect = read_value
        with patch.object(browser_launch, "winreg", registry):
            self.assertEqual(list(browser_launch._registry_candidates()),
                             ["user-path"] * 3 + ["machine-path"] * 3)
        self.assertEqual([query[0] for query in queries], ["user"] * 3 + ["machine"] * 3)
        self.assertEqual([query[3] for query in queries[:3]], [1, 3, 5])
        self.assertTrue(all(query[1] == browser_launch._APP_PATH for query in queries))

    def test_missing_or_unreadable_registry_keys_are_ignored(self):
        registry = MagicMock()
        registry.KEY_READ = 1
        registry.KEY_WOW64_64KEY = 2
        registry.KEY_WOW64_32KEY = 4
        registry.OpenKey.side_effect = OSError("Missing key")
        with patch.object(browser_launch, "winreg", registry):
            self.assertEqual(list(browser_launch._registry_candidates()), [])


if __name__ == "__main__":
    unittest.main()
