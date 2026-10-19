from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naiwa import PetWindow
from pet_core import Preferences


ROOT = Path(__file__).resolve().parents[1]


class SleepPreferencesTest(unittest.TestCase):
    def test_old_settings_enable_auto_sleep_without_losing_existing_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"size": 140, "speech": False, "auto_walk": False}),
                            encoding="utf-8")
            preferences = Preferences.load(path)
            self.assertTrue(preferences.auto_sleep)
            self.assertEqual(preferences.size, 140)
            self.assertFalse(preferences.speech)
            self.assertFalse(preferences.auto_walk)

    def test_auto_sleep_off_survives_save_and_invalid_type_uses_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            Preferences(auto_sleep=False).save(path)
            self.assertFalse(Preferences.load(path).auto_sleep)
            path.write_text(json.dumps({"auto_sleep": "false"}), encoding="utf-8")
            self.assertTrue(Preferences.load(path).auto_sleep)


class SleepInteractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        browser_patch = patch("naiwa.open_chatgpt")
        self.open_chatgpt = browser_patch.start()
        self.addCleanup(browser_patch.stop)
        startup_patch = patch("naiwa.is_autostart_enabled", return_value=False)
        startup_patch.start()
        self.addCleanup(startup_patch.stop)
        self.folder = tempfile.TemporaryDirectory(prefix="奶娃睡眠-")
        self.base = 1000.0
        with patch("naiwa.time.monotonic", return_value=self.base):
            self.pet = PetWindow(ROOT / "assets", Path(self.folder.name) / "settings.json",
                                 enable_tray=False)
            self.pet.preferences.auto_walk = False
            self.pet.preferences.auto_actions = False
            self.pet.preferences.follow_cursor = False
            self.pet.show_pet()
            self.app.processEvents()
        self.pet.timer.stop()
        self.pet.action = "idle"
        self.pet.action_until = 0
        self.pet.last_interaction = self.base
        self.point = self.pet.pet_rect().center()

    def tearDown(self):
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=self.point)
        self.pet.timer.stop()
        if self.pet.panel:
            self.pet.panel.close()
            self.pet.panel.deleteLater()
        self.pet.hide()
        self.pet.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def _at(self, now, callback, *args, **kwargs):
        with patch("naiwa.time.monotonic", return_value=now):
            return callback(*args, **kwargs)

    def _tick(self, now):
        self._at(now, self.pet._tick)

    def _sleep(self, now=None):
        result = self._at(self.base if now is None else now, self.pet.sleep)
        self.assertTrue(result)
        self.assertTrue(self.pet.sleeping)

    def test_auto_sleep_starts_at_ten_minutes_and_not_before(self):
        self.assertEqual(self.pet.AUTO_SLEEP_SECONDS, 600)
        self._tick(self.base + 599.9)
        self.assertFalse(self.pet.sleeping)
        self._tick(self.base + 600)
        self.assertTrue(self.pet.sleeping)
        self.assertEqual(self.pet.action, "sleep")

    def test_automatic_animation_does_not_postpone_sleep(self):
        self._at(self.base + 590, self.pet.play, "wave", speak=False, automatic=True)
        self.assertEqual(self.pet.action, "wave")
        self.assertEqual(self.pet.last_interaction, self.base)
        self._tick(self.base + 600)
        self.assertTrue(self.pet.sleeping)

    def test_sleep_stops_walking_and_loops_without_random_actions(self):
        self._at(self.base, self.pet._start_walk, self.base)
        self.assertGreater(self.pet.walk_until, 0)
        self._sleep(self.base + 1)
        self.assertEqual(self.pet.walk_until, 0)
        self.assertTrue(math.isinf(self.pet.action_until))
        self.assertTrue(self.pet.timer.isActive())
        before = self.pet.pos()
        self.pet.preferences.auto_walk = True
        self.pet.preferences.auto_actions = True
        self.pet.next_roam = self.pet.next_custom_action = 0
        clip = self.pet.clips["sleep"]
        started = self.pet.action_started
        with (patch.object(self.pet, "_start_walk") as walk,
              patch.object(self.pet, "_start_random_action") as random_action):
            self._tick(started + 1.1 / clip.fps)
            first_frame = self._at(started + 1.1 / clip.fps, self.pet._current_frame)
            self._tick(started + (clip.count + 1.1) / clip.fps)
            looped_frame = self._at(started + (clip.count + 1.1) / clip.fps,
                                    self.pet._current_frame)
            self._tick(started + 3600)
            walk.assert_not_called()
            random_action.assert_not_called()
        self.assertEqual(first_frame, looped_frame)
        self.assertEqual(first_frame[0], "sleep")
        self.assertEqual(self.pet.pos(), before)
        self.assertTrue(self.pet.sleeping)
        self.assertEqual(self.pet.action, "sleep")

    def test_pausing_freezes_sleep_and_resuming_preserves_sleep(self):
        self._sleep()
        self._at(self.base + 0.2, self.pet.toggle_pause)
        self.assertTrue(self.pet.paused)
        self.assertFalse(self.pet.timer.isActive())
        frame = self._at(self.base + 1, self.pet._current_frame)
        self.assertEqual(self._at(self.base + 100, self.pet._current_frame), frame)
        self._at(self.base + 100, self.pet.toggle_pause)
        self.assertTrue(self.pet.sleeping)
        self.assertEqual(self.pet.action, "sleep")
        self.assertTrue(self.pet.timer.isActive())

    def test_sleeping_pet_first_click_only_wakes_second_click_laughs(self):
        self._sleep()
        self._at(self.base + 1, QTest.mouseClick, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self.assertFalse(self.pet.sleeping)
        self.assertEqual(self.pet.action, "idle")
        self.assertEqual(self.pet.last_interaction, self.base + 1)
        self._at(self.base + 2, QTest.mouseClick, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self.assertEqual(self.pet.action, "laugh")
        self.open_chatgpt.assert_not_called()

    def test_drag_wakes_pet_and_plays_existing_drag_animation(self):
        self._sleep()
        self.assertIsNotNone(self.pet.drag_action)
        self._at(self.base + 1, QTest.mousePress, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self._at(self.base + 1.1, QTest.mouseMove, self.pet, self.point + QPoint(60, 25))
        self.assertFalse(self.pet.sleeping)
        self.assertTrue(self.pet.dragging)
        self.assertEqual(self.pet.action, self.pet.drag_action)
        self.assertFalse(self._at(self.base + 1.2, self.pet.sleep))
        self.assertEqual(self.pet.action, self.pet.drag_action)
        self._at(self.base + 2, QTest.mouseRelease, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self.assertFalse(self.pet.sleeping)
        self.assertEqual(self.pet.action, "idle")
        self.assertEqual(self.pet.last_interaction, self.base + 2)

    def test_hover_and_opening_controls_do_not_wake_pet(self):
        self._sleep()
        enter = QEnterEvent(QPointF(self.point), QPointF(self.point),
                            QPointF(self.pet.mapToGlobal(self.point)))
        self._at(self.base + 1, self.app.sendEvent, self.pet, enter)
        self.assertTrue(self.pet.sleeping)
        self._at(self.base + 2, self.pet._menu_started)
        self.assertTrue(self.pet.sleeping)
        self._at(self.base + 3, self.pet._menu_finished)
        self._at(self.base + 4, self.pet.open_panel)
        self.assertTrue(self.pet.sleeping)
        self.assertEqual(self.pet.action, "sleep")

    def test_manual_action_wakes_and_reschedules_automatic_behaviour(self):
        self._sleep()
        self._at(self.base + 1, self.pet.play, "wave", speak=False, automatic=True)
        self.assertTrue(self.pet.sleeping)
        self._at(self.base + 2, self.pet.play, "wave", speak=False)
        self.assertFalse(self.pet.sleeping)
        self.assertEqual(self.pet.action, "wave")
        self.assertEqual(self.pet.last_interaction, self.base + 2)
        self.assertGreater(self.pet.next_roam, self.base + 2)
        self.assertGreater(self.pet.next_custom_action, self.base + 2)

    def test_manual_wake_restarts_idle_countdown(self):
        self._sleep()
        self.assertTrue(self._at(self.base + 100, self.pet.wake, speak=False))
        self.assertEqual(self.pet.last_interaction, self.base + 100)
        self.assertGreater(self.pet.next_roam, self.base + 100)
        self.assertGreater(self.pet.next_custom_action, self.base + 100)
        self._tick(self.base + 699.9)
        self.assertFalse(self.pet.sleeping)
        self._tick(self.base + 700)
        self.assertTrue(self.pet.sleeping)

    def test_auto_sleep_is_suppressed_while_mouse_is_held(self):
        self._at(self.base + 1, QTest.mousePress, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self._tick(self.base + 1000)
        self.assertFalse(self.pet.sleeping)
        self.assertIsNotNone(self.pet.drag_anchor)
        self._at(self.base + 1001, QTest.mouseRelease, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self.assertEqual(self.pet.last_interaction, self.base + 1001)

    def test_menu_and_home_panel_defer_sleep_and_restart_countdown_on_close(self):
        self._at(self.base + 1, self.pet._menu_started)
        self._tick(self.base + 1000)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 1001, self.pet._menu_finished)
        self.assertEqual(self.pet.last_interaction, self.base + 1001)
        self._tick(self.base + 1600.9)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 1601, self.pet.open_panel)
        self._tick(self.base + 2601)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 2602, self.pet.panel.close)
        self.assertEqual(self.pet.last_interaction, self.base + 2602)
        self._tick(self.base + 3201.9)
        self.assertFalse(self.pet.sleeping)
        self._tick(self.base + 3202)
        self.assertTrue(self.pet.sleeping)

    def test_paused_or_hidden_pet_does_not_sleep_on_return(self):
        self._at(self.base + 1, self.pet.toggle_pause)
        self._tick(self.base + 1000)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 1001, self.pet.toggle_pause)
        self.assertEqual(self.pet.last_interaction, self.base + 1001)
        self._tick(self.base + 1002)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 1003, self.pet.hide)
        self._tick(self.base + 3000)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 3001, self.pet.show_pet)
        self.assertEqual(self.pet.last_interaction, self.base + 3001)
        self._tick(self.base + 3002)
        self.assertFalse(self.pet.sleeping)

    def test_home_sleep_control_and_auto_sleep_switch_are_independent(self):
        self._at(self.base, self.pet.open_panel)
        panel = self.pet.panel
        awake_text = panel.sleep_button.text()
        self._at(self.base + 1, panel.sleep_button.click)
        self.assertTrue(self.pet.sleeping)
        self.assertNotEqual(panel.sleep_button.text(), awake_text)
        self._at(self.base + 2, panel.checks["auto_sleep"].setChecked, False)
        self.assertTrue(self.pet.sleeping)
        self.assertFalse(self.pet.preferences.auto_sleep)
        self.assertFalse(Preferences.load(self.pet.config_path).auto_sleep)
        self._at(self.base + 3, panel.sleep_button.click)
        self.assertFalse(self.pet.sleeping)
        self._at(self.base + 4, panel.close)
        self._tick(self.base + 10000)
        self.assertFalse(self.pet.sleeping)


if __name__ == "__main__":
    unittest.main()
