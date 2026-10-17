from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from naiwa import PetWindow, SpriteAtlas
from pet_core import Preferences, load_custom_actions


ROOT = Path(__file__).resolve().parents[1]


class DragActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        browser_patch = patch("naiwa.open_chatgpt")
        self.open_chatgpt = browser_patch.start()
        self.addCleanup(browser_patch.stop)
        self.folder = tempfile.TemporaryDirectory(prefix="奶娃拖动-")
        self.assets = Path(self.folder.name) / "assets"
        (self.assets / "naifrog").mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "naifrog" / "spritesheet.webp", self.assets / "naifrog")
        self.action_folder = self.assets / "actions"
        self.action_folder.mkdir()
        self.entries = []
        for name, label in [("q_wave", "摆摆手"), ("q_wiggle", "扭扭肚子"), ("q_drag", "骑狗兜风")]:
            sheet = QPixmap(192 * 4, 208)
            sheet.fill(Qt.GlobalColor.transparent)
            painter = QPainter(sheet)
            for index in range(4):
                painter.fillRect(index * 192 + 30, 45, 110, 150, QColor(40 + index * 30, 130, 80))
            painter.end()
            self.assertTrue(sheet.save(str(self.action_folder / f"{name}.png")))
            entry = {"id": name, "name": label, "sheet": f"{name}.png",
                     "frame_width": 192, "frame_height": 208, "frame_count": 4,
                     "fps": 10, "loops": 1, "random": name != "q_drag"}
            if name == "q_drag":
                entry["trigger"] = "drag"
            self.entries.append(entry)
        self._write_manifest()
        self.pet = PetWindow(self.assets, Path(self.folder.name) / "settings.json", enable_tray=False)
        self.pet.preferences.follow_cursor = False
        self.pet.show_pet()
        self.app.processEvents()
        self.pet.timer.stop()
        self.pet.move(80, 80)
        self.point = self.pet.pet_rect().center()

    def tearDown(self):
        # QTest's button state must be released even when testing a lost release.
        QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton, pos=self.point)
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

    def _press(self, now=1000.0):
        with patch("naiwa.time.monotonic", return_value=now):
            QTest.mousePress(self.pet, Qt.MouseButton.LeftButton, pos=self.point)
        self.assertTrue(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)

    def _move(self, now=1000.1, offset=None):
        with patch("naiwa.time.monotonic", return_value=now):
            QTest.mouseMove(self.pet, self.point + (offset or QPoint(60, 25)))

    def _release(self, now=1001.0, position=None):
        with patch("naiwa.time.monotonic", return_value=now):
            QTest.mouseRelease(self.pet, Qt.MouseButton.LeftButton,
                               pos=position if position is not None else self.point)

    def _tick(self, now):
        with patch("naiwa.time.monotonic", return_value=now):
            self.pet._tick()

    def test_real_drag_starts_at_first_frame_and_each_new_drag_restarts(self):
        self._press()
        self.assertFalse(self.pet.dragging)
        self.assertNotEqual(self.pet.action, "q_drag")
        self._move(1000.1)
        self.assertTrue(self.pet.dragging)
        self.assertEqual(self.pet.action, "q_drag")
        with patch("naiwa.time.monotonic", return_value=1000.1):
            self.assertEqual(self.pet._current_frame(), ("q_drag", 0))
        self._move(1000.25)
        self.assertEqual(self.pet.action_started, 1000.1)
        self._release(1000.3)
        self.assertEqual(self.pet.action, "idle")
        self._press(1001)
        self._move(1001.1)
        self.assertEqual(self.pet.action_started, 1001.1)
        with patch("naiwa.time.monotonic", return_value=1001.1):
            self.assertEqual(self.pet._current_frame(), ("q_drag", 0))

    def test_drag_keeps_animating_and_looping_without_further_mouse_moves(self):
        self._press()
        self._move(1000.1)
        self.assertEqual(self.pet._display_key[1], 0)
        self._tick(1000.25)
        self.assertEqual(self.pet._display_key[:2], ("q_drag", 1))
        self._tick(1000.45)
        self.assertEqual(self.pet._display_key[:2], ("q_drag", 3))
        self._tick(1002.35)
        self.assertEqual(self.pet._display_key[:2], ("q_drag", 2))
        self.assertEqual(self.pet.action, "q_drag")
        self.assertTrue(self.pet.timer.isActive())

    def test_paused_pet_plays_drag_and_restores_paused_idle_on_release(self):
        with patch("naiwa.time.monotonic", return_value=999):
            self.pet.toggle_pause()
        self.assertFalse(self.pet.timer.isActive())
        self._press()
        self._move(1000.1)
        self.assertTrue(self.pet.paused)
        self.assertTrue(self.pet.timer.isActive())
        self._tick(1000.35)
        self.assertEqual(self.pet._display_key[:2], ("q_drag", 2))
        self._release()
        self.assertTrue(self.pet.paused)
        self.assertEqual(self.pet.action, "idle")
        self.assertFalse(self.pet.timer.isActive())
        with patch("naiwa.time.monotonic", return_value=1005):
            self.assertEqual(self.pet._current_frame(), ("idle", 0))
            self.pet.toggle_pause()
        self.assertFalse(self.pet.paused)
        self.assertTrue(self.pet.timer.isActive())

    def test_click_and_small_jitter_still_trigger_laughter(self):
        self._press()
        self._move(offset=QPoint(1, 1))
        self.assertFalse(self.pet.dragging)
        self.assertNotEqual(self.pet.action, "q_drag")
        self._release()
        self.assertEqual(self.pet.action, "laugh")
        self.assertIsNone(self.pet.drag_anchor)
        self.open_chatgpt.assert_not_called()

    def test_distant_release_without_move_does_not_open_browser(self):
        self._press()
        self._release(position=self.point + QPoint(70, 40))
        self.assertFalse(self.pet.dragging)
        self.assertIsNone(self.pet.drag_anchor)
        self.open_chatgpt.assert_not_called()

    def test_drag_preempts_walk_and_is_not_interrupted_by_random_or_manual_actions(self):
        self.pet._start_walk(999)
        self._press()
        self._move()
        self.pet.next_roam = self.pet.next_custom_action = 0
        with (patch.object(self.pet, "_start_walk") as walk,
              patch.object(self.pet, "_start_random_action") as automatic):
            self._tick(1010.25)
            walk.assert_not_called()
            automatic.assert_not_called()
        self.assertFalse(self.pet._start_random_action(1010.25))
        self.pet.play("q_wave", automatic=True)
        self.pet.play("laugh")
        self.assertEqual(self.pet.action, "q_drag")
        self.assertEqual(self.pet.walk_until, 0)
        self._release(1010.3)
        self.assertTrue(self.pet._can_start_automatic())
        self.assertGreater(self.pet.next_roam, 1010.3)
        self.assertGreater(self.pet.next_custom_action, 1010.3)

    def test_release_outside_pet_saves_position_and_stops_drag_action(self):
        before = self.pet.pos()
        self._press()
        self._move()
        self._release(position=QPoint(-100, -100))
        self.assertNotEqual(self.pet.pos(), before)
        settings = Preferences.load(self.pet.config_path)
        self.assertEqual((settings.x, settings.y), (self.pet.x(), self.pet.y()))
        self.assertFalse(self.pet.dragging)
        self.assertIsNone(self.pet.press_position)
        self.assertIsNone(self.pet.drag_anchor)
        self.assertEqual(self.pet.action, "idle")
        self.open_chatgpt.assert_not_called()

    def test_watchdog_recovers_when_release_event_was_lost(self):
        self._press()
        self._move()
        with patch.object(QApplication, "mouseButtons", return_value=Qt.MouseButton.NoButton):
            self._tick(1001)
        self.assertIsNone(self.pet.drag_anchor)
        self.assertFalse(self.pet.dragging)
        self.assertEqual(self.pet.action, "idle")
        self.assertTrue(self.pet._can_start_automatic())
        self.open_chatgpt.assert_not_called()

    def test_capture_loss_deactivation_and_hide_do_not_leave_drag_stuck(self):
        for kind in [QEvent.Type.UngrabMouse, QEvent.Type.WindowDeactivate, QEvent.Type.Hide]:
            with self.subTest(event=kind):
                self._press()
                self._move()
                self.app.sendEvent(self.pet, QEvent(kind))
                self.app.processEvents()
                self.assertIsNone(self.pet.drag_anchor)
                self.assertFalse(self.pet.dragging)
                self.assertEqual(self.pet.action, "idle")
                self._release()
        self.open_chatgpt.assert_not_called()

    def test_drag_trigger_is_never_random_or_a_manual_button(self):
        # Even a mistakenly enabled random flag must not select the drag clip.
        self.entries[-1]["random"] = True
        self.entries.append({**self.entries[-1], "id": "bad_trigger", "trigger": "unknown"})
        self._write_manifest()
        with self.assertLogs(level="WARNING"):
            actions = load_custom_actions(self.action_folder / "manifest.json")
        self.assertFalse(actions["q_drag"].random)
        self.assertEqual(actions["q_drag"].trigger, "drag")
        self.assertNotIn("bad_trigger", actions)
        self.assertNotIn("骑狗兜风", {item.text() for item in self.pet.menu.actions()})
        self.pet.open_panel()
        self.assertNotIn("q_drag", self.pet.panel.action_buttons)
        self.pet.panel.hide()
        for _ in range(8):
            self.pet.action = "idle"
            self.assertTrue(self.pet._start_random_action(1000))
            self.assertIn(self.pet.action, {"q_wave", "q_wiggle"})

    def test_missing_drag_sheet_keeps_original_drag_release_behavior(self):
        (self.action_folder / "q_drag.png").unlink()
        with self.assertLogs(level="WARNING"):
            atlas = SpriteAtlas(self.assets / "naifrog" / "spritesheet.webp")
        self.assertNotIn("q_drag", atlas.custom_actions)
        self.pet.drag_action = None
        self._press()
        self._move()
        self.assertTrue(self.pet.dragging)
        self.assertFalse(self.pet._drag_animation_active)
        self._release()
        self.assertEqual(self.pet.action, "wave")
        self.assertIsNone(self.pet.drag_anchor)


if __name__ == "__main__":
    unittest.main()
