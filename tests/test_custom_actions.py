from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from naiwa import PetWindow, SpriteAtlas
from pet_core import CLIPS, Preferences, frame_at, load_custom_actions


ROOT = Path(__file__).resolve().parents[1]


class CustomActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="奶娃新动作-")
        self.assets = Path(self.folder.name) / "assets"
        (self.assets / "naifrog").mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "naifrog" / "spritesheet.webp", self.assets / "naifrog")
        self.action_folder = self.assets / "actions"
        self.action_folder.mkdir()
        self.entries = []
        for name, label in [("q_wave", "摆摆手"), ("q_wiggle", "扭扭肚子")]:
            sheet = QPixmap(192 * 4, 208)
            sheet.fill(Qt.GlobalColor.transparent)
            painter = QPainter(sheet)
            for index in range(4):
                painter.fillRect(index * 192 + 30, 45, 110, 150, QColor(40 + index * 30, 130, 80))
            painter.end()
            self.assertTrue(sheet.save(str(self.action_folder / f"{name}.png")))
            self.entries.append({"id": name, "name": label, "sheet": f"{name}.png",
                                 "frame_width": 192, "frame_height": 208, "frame_count": 4,
                                 "fps": 10, "loops": 2, "random": True})
        self._write_manifest()
        self.pet = PetWindow(self.assets, Path(self.folder.name) / "settings.json", enable_tray=False)
        self.pet.preferences.auto_walk = False
        self.pet.preferences.follow_cursor = False
        self.pet.show_pet()
        self.app.processEvents()
        self.pet.timer.stop()

    def tearDown(self):
        self.pet.timer.stop()
        if self.pet.panel:
            self.pet.panel.close()
            self.pet.panel.deleteLater()
        self.pet.hide()
        self.pet.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def _write_manifest(self):
        (self.action_folder / "manifest.json").write_text(
            json.dumps({"version": 1, "actions": self.entries}, ensure_ascii=False), encoding="utf-8")

    def _idle_due(self, now=1000.0):
        self.pet.action = "idle"
        self.pet.action_started = now - 10
        self.pet.action_until = 0
        self.pet.walk_until = 0
        self.pet.next_custom_action = now - 1
        self.pet.next_roam = now - 1
        self.pet._last_tick = now - 0.05
        return now

    def _tick_at(self, now):
        with patch("naiwa.time.monotonic", return_value=now):
            self.pet._tick()

    def test_loads_new_sheets_without_changing_original_clips_or_look(self):
        self.assertEqual(set(self.pet.custom_actions), {"q_wave", "q_wiggle"})
        self.assertEqual(len(CLIPS), 9)
        self.assertNotIn("q_wave", CLIPS)
        self.assertEqual(set(self.pet.clips), set(CLIPS) | {"q_wave", "q_wiggle"})
        for name in self.pet.custom_actions:
            self.assertEqual(len(self.pet.atlas.frames[name]), 4)
            self.assertFalse(self.pet.atlas.mask(name, 3, 100).isEmpty())
            self.assertEqual(frame_at(name, 0.7, self.pet.clips), 3)
        self.assertEqual(len(self.pet.atlas.look), 16)

    def test_bad_metadata_and_missing_or_wrong_size_sheets_are_skipped(self):
        self.entries.extend([
            {**self.entries[0], "id": "idle"},
            {**self.entries[0], "id": "outside", "sheet": "../../outside.png"},
            {**self.entries[0], "id": "bad_fps", "fps": 0},
            {**self.entries[0], "id": "bad_count", "frame_count": True},
            {**self.entries[0], "id": "missing", "sheet": "missing.png"},
            {**self.entries[0], "id": "wrong_size", "frame_count": 3},
        ])
        self._write_manifest()
        with self.assertLogs(level="WARNING"):
            atlas = SpriteAtlas(self.assets / "naifrog" / "spritesheet.webp")
        self.assertEqual(set(atlas.custom_actions), {"q_wave", "q_wiggle"})
        self.assertEqual(load_custom_actions(self.action_folder / "absent.json"), {})

    def test_due_action_starts_while_free_walk_is_disabled(self):
        now = self._idle_due()
        self._tick_at(now)
        self.assertIn(self.pet.action, self.pet.custom_actions)
        self.assertEqual(self.pet.walk_until, 0)
        self.assertEqual(self.pet.action_until, now + 0.8)
        self.assertGreaterEqual(self.pet.next_custom_action, now + 0.8 + 12)
        self.assertLessEqual(self.pet.next_custom_action, now + 0.8 + 25)

    def test_action_plays_complete_loops_then_returns_to_idle(self):
        with patch("naiwa.time.monotonic", return_value=1000):
            self.pet.play("q_wave", speak=False)
        self._tick_at(1000.799)
        self.assertEqual(self.pet.action, "q_wave")
        with patch("naiwa.time.monotonic", return_value=1000.799):
            self.assertEqual(self.pet._current_frame(), ("q_wave", 3))
        self._tick_at(1000.8)
        self.assertEqual(self.pet.action, "idle")
        self.assertEqual(self.pet.timer.interval(), 100)
        self.assertGreaterEqual(self.pet.next_custom_action, 1012.8)

    def test_consecutive_automatic_actions_do_not_repeat(self):
        self._tick_at(self._idle_due())
        first = self.pet.action
        self._tick_at(self._idle_due(1100))
        self.assertNotEqual(first, self.pet.action)
        self.assertIn(self.pet.action, self.pet.custom_actions)

    def test_pause_drag_menu_hidden_and_panel_prevent_automatic_start(self):
        for condition in ["paused", "drag", "menu", "hidden", "panel"]:
            with self.subTest(condition=condition):
                self.pet.paused = condition == "paused"
                self.pet.drag_anchor = QPoint(5, 5) if condition == "drag" else None
                self.pet.menu_open = condition == "menu"
                if condition == "hidden":
                    self.pet.hide()
                if condition == "panel":
                    self.pet.open_panel()
                self._tick_at(self._idle_due())
                self.assertEqual(self.pet.action, "idle")
                self.assertEqual(self.pet.walk_until, 0)
                self.pet.paused = False
                self.pet.drag_anchor = None
                self.pet.menu_open = False
                self.pet.show_pet()
                self.pet.timer.stop()
                if self.pet.panel:
                    self.pet.panel.hide()

    def test_automatic_actions_do_not_interrupt_manual_action_or_walk(self):
        with patch("naiwa.time.monotonic", return_value=1000):
            self.pet.play("laugh", speak=False)
        self.pet.next_custom_action = 999
        self._tick_at(1000.1)
        self.assertEqual(self.pet.action, "laugh")
        self.pet._start_walk(1000.1)
        self.pet.next_custom_action = 999
        self._tick_at(1000.2)
        self.assertIn(self.pet.action, {"walk_left", "walk_right"})
        self.assertGreater(self.pet.walk_until, 1000.2)
        self.pet.set_preference("auto_actions", False)
        self.assertIn(self.pet.action, {"walk_left", "walk_right"})
        self.assertGreater(self.pet.walk_until, 1000.2)

    def test_disabling_new_actions_keeps_free_walk_and_persists_setting(self):
        self.assertTrue(self.pet.preferences.auto_actions)
        self.pet.set_preference("auto_actions", False)
        self.pet.preferences.auto_walk = True
        self._tick_at(self._idle_due())
        self.assertIn(self.pet.action, {"walk_left", "walk_right"})
        self.assertFalse(Preferences.load(self.pet.config_path).auto_actions)

    def test_new_actions_are_available_in_menu_and_panel(self):
        labels = {action.text(): action for action in self.pet.menu.actions()}
        self.assertIn("摆摆手", labels)
        self.assertIn("扭扭肚子", labels)
        labels["摆摆手"].trigger()
        self.assertEqual(self.pet.action, "q_wave")
        self.pet.open_panel()
        self.pet.panel.action_buttons["q_wiggle"].click()
        self.assertEqual(self.pet.action, "q_wiggle")
        self.assertEqual(self.pet.panel.status.text(), "扭扭肚子中")
        self.pet.panel.checks["auto_actions"].setChecked(False)
        self.assertFalse(self.pet.preferences.auto_actions)
        self.assertFalse(self.pet.auto_actions_action.isChecked())
        self.pet.auto_actions_action.trigger()
        self.assertTrue(self.pet.preferences.auto_actions)
        self.assertTrue(self.pet.panel.checks["auto_actions"].isChecked())

    def test_thirty_fps_survives_show_hide_and_pause_resume(self):
        action = self.pet.custom_actions["q_wave"]
        clip = replace(action.clip, fps=30)
        self.pet.custom_actions["q_wave"] = replace(action, clip=clip)
        self.pet.clips["q_wave"] = clip
        with patch("naiwa.time.monotonic", return_value=1000):
            self.pet.play("q_wave", speak=False)
            self.assertEqual(self.pet.timer.interval(), 33)
            self.assertAlmostEqual(self.pet.action_until, 1000 + 8 / 30)
            self.pet.show_pet()
            self.assertEqual(self.pet.timer.interval(), 33)
            self.pet.hide()
            self.pet.show_pet()
            self.assertEqual(self.pet.timer.interval(), 33)
            self.pet.toggle_pause()
        with patch("naiwa.time.monotonic", return_value=1005):
            self.pet.toggle_pause()
            self.assertEqual(self.pet.timer.interval(), 33)
            self.assertAlmostEqual(self.pet.action_until, 1005 + 8 / 30)
        self.pet.timer.stop()

    def test_ten_minutes_with_adverse_deadlines_never_starves_actions_or_walks(self):
        # Use the production clip lengths. Rendering is irrelevant to this
        # scheduling simulation, so fixture sheets can remain four frames long.
        for name, count in [("q_wave", 69), ("q_wiggle", 103)]:
            action = self.pet.custom_actions[name]
            clip = replace(action.clip, count=count, fps=30)
            self.pet.custom_actions[name] = replace(action, clip=clip)
            self.pet.clips[name] = clip
        self.pet.preferences.auto_walk = True
        self.pet.preferences.auto_actions = True
        for custom_delay, roam_delay in [(25, 18), (12, 35)]:
            with self.subTest(custom_delay=custom_delay, roam_delay=roam_delay):
                clock = [self._idle_due()]
                self.pet.next_custom_action = clock[0] + custom_delay
                self.pet.next_roam = clock[0] + roam_delay
                self.pet.last_custom_action = None

                def interval(low, high):
                    if (low, high) == (12, 25):
                        return custom_delay
                    if (low, high) == (18, 35):
                        return roam_delay
                    return low

                with (patch("naiwa.time.monotonic", side_effect=lambda: clock[0]),
                      patch("naiwa.random.uniform", side_effect=interval),
                      patch.object(self.pet, "_refresh_frame"),
                      patch.object(self.pet, "save_preferences"),
                      patch.object(self.pet, "_start_walk", wraps=self.pet._start_walk) as walks,
                      patch.object(self.pet, "play", wraps=self.pet.play) as plays):
                    for step in range(6001):
                        clock[0] = 1000 + step / 10
                        self.pet._tick()
                        if self.pet.walk_until:
                            self.assertIn(self.pet.action, {"walk_left", "walk_right"})
                    counts = Counter(call.args[0] for call in plays.call_args_list
                                     if call.kwargs.get("automatic"))
                    self.assertGreater(walks.call_count, 5)
                    self.assertGreater(counts["q_wave"], 5)
                    self.assertGreater(counts["q_wiggle"], 5)


if __name__ == "__main__":
    unittest.main()
