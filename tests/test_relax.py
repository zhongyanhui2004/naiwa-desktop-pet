from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naiwa import PetWindow
from pet_core import Preferences


ROOT = Path(__file__).resolve().parents[1]


class RelaxPreferencesTest(unittest.TestCase):
    def test_legacy_sound_choice_is_ignored_and_removed_without_resetting_preferences(self):
        for legacy_sound in (True, False):
            with self.subTest(sound_enabled=legacy_sound), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "settings.json"
                path.write_text(json.dumps({"size": 140, "speech": False,
                                            "auto_sleep": False, "sound_enabled": legacy_sound}),
                                encoding="utf-8")
                preferences = Preferences.load(path)
                self.assertFalse(hasattr(preferences, "sound_enabled"))
                self.assertEqual(preferences.size, 140)
                self.assertFalse(preferences.speech)
                self.assertFalse(preferences.auto_sleep)
                preferences.save(path)
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("sound_enabled", saved)
                self.assertEqual(Preferences.load(path), preferences)


class RelaxInteractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        startup_patch = patch("naiwa.is_autostart_enabled", return_value=False)
        startup_patch.start()
        self.addCleanup(startup_patch.stop)
        self.folder = tempfile.TemporaryDirectory(prefix="奶娃放松-")
        self.base = 1000.0
        self.config = Path(self.folder.name) / "settings.json"
        self.pet = self._new_pet()
        self.point = self.pet.pet_rect().center()

    def _new_pet(self):
        with patch("naiwa.time.monotonic", return_value=self.base):
            pet = PetWindow(ROOT / "assets", self.config, enable_tray=False)
            pet.preferences.auto_walk = False
            pet.preferences.auto_actions = False
            pet.preferences.follow_cursor = False
            pet.show_pet()
            self.app.processEvents()
        pet.timer.stop()
        pet.action = "idle"
        pet.action_until = 0
        return pet

    def _dispose_pet(self):
        self.pet.timer.stop()
        if self.pet.panel:
            self.pet.panel.close()
            self.pet.panel.deleteLater()
        self.pet.hide()
        self.pet.deleteLater()
        self.app.processEvents()

    def tearDown(self):
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=self.point)
        self._dispose_pet()
        self.folder.cleanup()

    def _at(self, now, callback, *args, **kwargs):
        with patch("naiwa.time.monotonic", return_value=now):
            return callback(*args, **kwargs)

    def _play(self, now=None):
        self._at(self.base if now is None else now, self.pet.play, "relax", speak=False)

    def test_relax_is_visible_and_manual_only_then_returns_to_idle_after_one_cycle(self):
        metadata = self.pet.custom_actions["relax"]
        self.assertEqual(metadata.clip.label, "放松放屁")
        self.assertFalse(metadata.random)
        self.assertIsNone(metadata.trigger)
        self.assertEqual(metadata.loops, 1)
        self.assertEqual(metadata.clip.count, 4)
        for index in range(metadata.clip.count):
            self.assertFalse(self.pet.atlas.mask("relax", index, 100).isEmpty())
        self._play()
        self.assertEqual(self.pet.action, "relax")
        self.assertEqual(self.pet.walk_until, 0)
        duration = metadata.clip.count / metadata.clip.fps
        self.assertEqual(duration, 4)
        self.assertAlmostEqual(self.pet.action_until, self.base + duration)
        self._at(self.pet.action_until - 0.001, self.pet._tick)
        self.assertEqual(self.pet.action, "relax")
        self._at(self.pet.action_until, self.pet._tick)
        self.assertEqual(self.pet.action, "idle")

    def test_menu_and_home_button_each_start_the_action(self):
        actions = {action.text(): action for action in self.pet.menu.actions()}
        self.assertIn("放松放屁", actions)
        self._at(self.base, actions["放松放屁"].trigger)
        self.assertEqual(self.pet.action, "relax")
        self._at(self.base + 1, self.pet.open_panel)
        self.assertEqual(self.pet.panel.action_buttons["relax"].text(), "放松放屁")
        self._at(self.base + 2, self.pet.panel.action_buttons["relax"].click)
        self.assertEqual(self.pet.action, "relax")
        self.assertEqual(self.pet.panel.status.text(), "放松放屁中")

    def test_random_activity_never_selects_relax(self):
        self.pet.preferences.auto_actions = True
        with patch("naiwa.random.choice", side_effect=lambda choices: choices[0]) as choose:
            self.assertTrue(self._at(self.base, self.pet._start_random_action, self.base))
        self.assertNotIn("relax", choose.call_args.args[0])
        self.assertNotEqual(self.pet.action, "relax")

    def test_manual_relax_wakes_sleeping_pet_and_resumes_a_paused_pet(self):
        self.assertTrue(self._at(self.base, self.pet.sleep))
        self._play(self.base + 1)
        self.assertFalse(self.pet.sleeping)
        self.assertEqual(self.pet.action, "relax")
        self._at(self.base + 2, self.pet.toggle_pause)
        self.assertTrue(self.pet.paused)
        self._play(self.base + 3)
        self.assertFalse(self.pet.paused)
        self.assertTrue(self.pet.timer.isActive())
        self.assertEqual(self.pet.action, "relax")

    def test_drag_replaces_relax_and_cannot_be_interrupted_by_relax(self):
        self._play()
        self._at(self.base + 0.1, QTest.mousePress, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self._at(self.base + 0.2, QTest.mouseMove, self.pet, self.point + QPoint(60, 25))
        self.assertTrue(self.pet.dragging)
        self.assertEqual(self.pet.action, self.pet.drag_action)
        self._play(self.base + 0.3)
        self.assertEqual(self.pet.action, self.pet.drag_action)
        self._at(self.base + 0.4, QTest.mouseRelease, self.pet, Qt.MouseButton.LeftButton,
                 pos=self.point)
        self.assertEqual(self.pet.action, "idle")

    def test_sleep_and_other_action_can_replace_relax(self):
        self._play()
        self.assertTrue(self._at(self.base + 0.1, self.pet.sleep))
        self.assertTrue(self.pet.sleeping)
        self.assertEqual(self.pet.action, self.pet.sleep_action)
        self._play(self.base + 1)
        self._at(self.base + 1.1, self.pet.play, "wave", speak=False)
        self.assertFalse(self.pet.sleeping)
        self.assertEqual(self.pet.action, "wave")

    def test_pause_freezes_relax_and_resume_preserves_remaining_duration(self):
        self._play()
        self._at(self.base + 1, self.pet.toggle_pause)
        self.assertTrue(self.pet.paused)
        self.assertFalse(self.pet.timer.isActive())
        frozen = self._at(self.base + 2, self.pet._current_frame)
        self.assertEqual(self._at(self.base + 5, self.pet._current_frame), frozen)
        self._at(self.base + 6, self.pet.toggle_pause)
        self.assertFalse(self.pet.paused)
        self.assertTrue(self.pet.timer.isActive())
        self.assertAlmostEqual(self.pet.action_until, self.base + 9)

    def test_pet_and_home_menu_offer_no_audio_controls(self):
        self._at(self.base, self.pet.open_panel)
        self.assertNotIn("sound_enabled", self.pet.panel.checks)
        for action in self.pet.menu.actions():
            self.assertNotIn("音效", action.text())
            self.assertNotIn("静音", action.text())
        self.assertFalse(hasattr(self.pet, "sound_effects"))
        self.assertFalse(hasattr(self.pet, "sound_action"))


if __name__ == "__main__":
    unittest.main()
