from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naiwa import PetWindow
from pet_core import CLIPS, Preferences, look_direction


ROOT = Path(__file__).resolve().parents[1]


class PreferencesTest(unittest.TestCase):
    def test_chinese_directory_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="奶娃测试-") as folder:
            path = Path(folder) / "设置" / "settings.json"
            original = Preferences(size=145, x=-750, y=350, speech=False)
            original.save(path)
            self.assertEqual(Preferences.load(path), original)

    def test_corrupt_settings_do_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text("{ broken", encoding="utf-8")
            with self.assertLogs(level="WARNING"):
                self.assertEqual(Preferences.load(path), Preferences())

    def test_wrong_types_are_ignored_and_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"size": 99999, "auto_walk": "false", "x": True, "speech": False}))
            settings = Preferences.load(path)
            self.assertEqual(settings.size, 180)
            self.assertTrue(settings.auto_walk)
            self.assertIsNone(settings.x)
            self.assertFalse(settings.speech)


class InteractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        browser_patch = patch("naiwa.open_chatgpt")
        self.open_chatgpt = browser_patch.start()
        self.addCleanup(browser_patch.stop)
        self.startup_state = {"enabled": True}
        startup_read = patch("naiwa.is_autostart_enabled", side_effect=lambda: self.startup_state["enabled"])
        self.startup_read = startup_read.start()
        self.addCleanup(startup_read.stop)
        startup_write = patch("naiwa.set_autostart_enabled",
                              side_effect=lambda value: self.startup_state.update(enabled=value))
        self.startup_write = startup_write.start()
        self.addCleanup(startup_write.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.pet = PetWindow(ROOT / "assets", Path(self.folder.name) / "settings.json", enable_tray=False)
        self.pet.preferences.auto_walk = False
        self.pet.preferences.follow_cursor = False
        self.pet.show_pet()
        self.app.processEvents()

    def tearDown(self):
        self.pet.timer.stop()
        if self.pet.panel:
            self.pet.panel.close()
            self.pet.panel.deleteLater()
        self.pet.hide()
        self.pet.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def test_all_playable_cells_and_look_directions_contain_visible_pixels(self):
        for name, clip in CLIPS.items():
            for index in range(clip.count):
                self.assertFalse(self.pet.atlas.mask(name, index, 100).isEmpty(), (name, index))
        for index in range(16):
            self.assertFalse(self.pet.atlas.mask("look", index, 100).isEmpty(), index)

    def test_click_triggers_laughter_and_returns_to_idle(self):
        QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=self.pet.pet_rect().center())
        self.assertEqual(self.pet.action, "laugh")
        self.assertIn("哈哈", self.pet.bubble_text)
        self.open_chatgpt.assert_not_called()
        future = self.pet.action_until + 0.1
        with patch("naiwa.time.monotonic", return_value=future):
            self.pet._tick()
        self.assertEqual(self.pet.action, "idle")

    def test_each_separate_click_only_triggers_laughter(self):
        for _ in range(3):
            QTest.mouseClick(self.pet, Qt.MouseButton.LeftButton, pos=self.pet.pet_rect().center())
            self.assertEqual(self.pet.action, "laugh")
        self.open_chatgpt.assert_not_called()

    def test_panel_chatgpt_button_opens_once_per_click(self):
        self.pet.open_panel()
        for expected_calls in range(1, 4):
            self.pet.panel.chatgpt_button.click()
            self.assertEqual(self.open_chatgpt.call_count, expected_calls)
        self.assertEqual(self.pet.panel.chatgpt_status.text(), "已用谷歌浏览器打开 ChatGPT。")

    def test_creating_and_showing_panel_does_not_open_browser(self):
        self.pet.open_panel()
        self.app.processEvents()
        self.pet.panel.hide()
        self.pet.open_panel()
        self.app.processEvents()
        self.open_chatgpt.assert_not_called()

    def test_panel_startup_toggle_reads_system_state_and_survives_reopen(self):
        self.pet.open_panel()
        button = self.pet.panel.startup_button
        self.assertTrue(button.isChecked())
        self.assertIn("已开启", button.text())
        self.startup_write.assert_not_called()
        button.click()
        self.startup_write.assert_called_once_with(False)
        self.assertFalse(button.isChecked())
        self.assertIn("已关闭", button.text())
        self.pet.panel.hide()
        self.pet.open_panel()
        self.assertFalse(button.isChecked())
        self.assertEqual(self.startup_write.call_count, 1)
        button.click()
        self.assertTrue(button.isChecked())
        self.assertTrue(self.startup_state["enabled"])
        self.assertEqual(self.startup_write.call_count, 2)
        self.open_chatgpt.assert_not_called()

    def test_startup_write_failure_restores_actual_system_state(self):
        self.pet.open_panel()
        self.startup_write.side_effect = PermissionError("Cannot write the registry")
        with self.assertLogs(level="ERROR"):
            self.pet.panel.startup_button.click()
        self.assertTrue(self.pet.panel.startup_button.isChecked())
        self.assertIn("已开启", self.pet.panel.startup_button.text())
        self.assertIn("失败", self.pet.panel.startup_error.text())
        self.assertFalse(self.pet.panel.startup_error.isHidden())

    def test_browser_failure_is_reported_in_panel_without_breaking_pet(self):
        self.pet.open_panel()
        self.open_chatgpt.side_effect = FileNotFoundError("Chrome is not installed")
        with self.assertLogs(level="ERROR"):
            self.pet.panel.chatgpt_button.click()
        self.assertIsNone(self.pet.drag_anchor)
        self.assertEqual(self.pet.panel.chatgpt_status.text(), "没有打开谷歌浏览器，请检查 Chrome 是否安装。")
        self.assertTrue(self.pet.timer.isActive())

    def test_right_button_and_panel_animations_do_not_open_browser(self):
        QTest.mousePress(self.pet, Qt.MouseButton.RightButton, pos=self.pet.pet_rect().center())
        QTest.mouseRelease(self.pet, Qt.MouseButton.RightButton, pos=self.pet.pet_rect().center())
        self.pet.open_panel()
        for button in self.pet.panel.action_buttons.values():
            button.click()
        self.open_chatgpt.assert_not_called()

    def test_drag_changes_and_persists_position(self):
        self.pet.move(80, 80)
        self.pet.action = "idle"
        self.pet.last_hover = time.monotonic()
        before = self.pet.pos()
        point = self.pet.pet_rect().center()
        QTest.mousePress(self.pet, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(self.pet, point + QPoint(60, 25))
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=point)
        self.assertNotEqual(self.pet.pos(), before)
        saved = Preferences.load(self.pet.config_path)
        self.assertEqual((saved.x, saved.y), (self.pet.x(), self.pet.y()))
        self.assertIsNone(self.pet.drag_anchor)
        self.open_chatgpt.assert_not_called()

    def test_pause_freezes_and_resume_restarts_animation_timer(self):
        self.pet.play("wave")
        self.pet.toggle_pause()
        frame = self.pet._current_frame()
        QTest.qWait(200)
        self.assertFalse(self.pet.timer.isActive())
        self.assertEqual(self.pet._current_frame(), frame)
        self.pet.toggle_pause()
        self.assertTrue(self.pet.timer.isActive())
        self.assertFalse(self.pet.paused)

    def test_walk_turns_at_screen_boundary_and_stops_when_disabled(self):
        area = self.app.primaryScreen().availableGeometry()
        self.pet.move(area.right() - self.pet.width() + 1, area.bottom() - self.pet.height() + 1)
        now = time.monotonic()
        self.pet._start_walk(now)
        self.pet.direction = 1
        self.pet._last_tick = now - 0.05
        with patch("naiwa.time.monotonic", return_value=now + 0.05):
            self.pet._tick()
        self.assertEqual(self.pet.direction, -1)
        self.assertTrue(area.contains(self.pet.geometry()))
        self.pet.set_preference("auto_walk", False)
        self.assertEqual(self.pet.action, "idle")
        self.assertEqual(self.pet.walk_until, 0)

    def test_old_monitor_position_recovers_and_resizing_stays_on_screen(self):
        self.pet.preferences.x = -99999
        self.pet.preferences.y = 99999
        self.pet._restore_position()
        self.pet.set_preference("size", 180)
        self.assertTrue(any(screen.availableGeometry().contains(self.pet.geometry()) for screen in self.app.screens()))

    def test_panel_controls_update_pet_and_persist_preferences(self):
        self.pet.open_panel()
        self.app.processEvents()
        self.pet.panel.slider.setValue(140)
        self.pet.panel.checks["speech"].setChecked(False)
        self.assertEqual(self.pet.preferences.size, 140)
        self.assertFalse(self.pet.preferences.speech)
        self.assertEqual(self.pet.bubble_text, "")
        saved = Preferences.load(self.pet.config_path)
        self.assertEqual(saved.size, 140)
        self.assertFalse(saved.speech)
        self.pet.panel.close()
        self.assertTrue(self.pet.isVisible())

    def test_topmost_toggle_preserves_location(self):
        before = self.pet.pos()
        self.pet.set_preference("always_on_top", False)
        self.assertEqual(self.pet.pos(), before)
        self.pet.set_preference("always_on_top", True)
        self.assertEqual(self.pet.pos(), before)

    def test_cursor_directions_match_the_atlas_order(self):
        self.assertEqual([look_direction(*vector) for vector in [(0, -100), (100, 0), (0, 100), (-100, 0)]], [0, 4, 8, 12])


if __name__ == "__main__":
    unittest.main()
