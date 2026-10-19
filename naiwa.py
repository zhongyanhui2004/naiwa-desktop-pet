"""A small Windows desktop companion using the upstream Naiwa atlas."""
from __future__ import annotations

import logging
import math
from pathlib import Path
import random
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QPushButton, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from autostart import is_enabled as is_autostart_enabled, set_enabled as set_autostart_enabled
from browser_launch import open_chatgpt
from version import APP_VERSION
from pet_core import (
    ATLAS_SIZE, CLIPS, FRAME_HEIGHT, FRAME_WIDTH, Preferences, clamp, frame_at,
    load_custom_actions, look_direction,
)


ACTION_TEXT = {
    "wave": ("挥挥手", "嗨～今天也陪着你！"),
    "laugh": ("大笑一下", "哈哈哈哈～开心最重要！"),
    "work": ("专心工作", "你忙你的，我陪你一起努力。"),
    "wait": ("左顾右盼", "让我看看，有什么新鲜事～"),
    "sad": ("委屈一下", "摸摸我，就又开心了。"),
    "think": ("抱胸思考", "嗯……先思考一下下。"),
}

PANEL_STYLE = """
QDialog { background: #f7f5ef; color: #302e26; }
QLabel { color: #302e26; background: transparent; }
QLabel#eyebrow { color: #89816c; font-size: 11px; font-weight: 700; }
QLabel#heading { font-size: 25px; font-weight: 700; }
QLabel#muted { color: #807966; font-size: 12px; }
QLabel#section { font-weight: 700; font-size: 13px; }
QLabel#badge { background: #eaeedc; color: #617238; border-radius: 11px; padding: 5px 10px; font-size: 11px; }
QFrame#card { background: #ffffff; border: 1px solid #e9e5da; border-radius: 16px; }
QPushButton { background: #fff; border: 1px solid #e6e1d5; border-radius: 10px; padding: 11px 14px; color: #504a3a; font-size: 13px; }
QPushButton:hover { background: #fff6d6; border-color: #e1c565; }
QPushButton:pressed { background: #f8e6a4; }
QPushButton#primary { background: #f4cd59; border-color: #f4cd59; color: #473a12; font-weight: 700; }
QPushButton#primary:hover { background: #f7d978; }
QPushButton#quiet { background: transparent; border: none; padding: 5px; color: #81785e; font-size: 11px; }
QPushButton#autostart { padding: 5px 9px; font-size: 12px; }
QPushButton#autostart:checked { background: #fff3c1; border-color: #dfc36d; }
QCheckBox { color: #544f41; font-size: 12px; spacing: 9px; padding: 4px 0; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #d7d0bf; border-radius: 5px; background: #fff; }
QCheckBox::indicator:checked { background: #edc751; border-color: #d6ad36; image: none; }
QSlider::groove:horizontal { height: 5px; border-radius: 2px; background: #eee9db; }
QSlider::sub-page:horizontal { background: #edc751; border-radius: 2px; }
QSlider::handle:horizontal { width: 17px; margin: -6px 0; border-radius: 8px; background: #d7a92a; }
"""


class SpriteAtlas:
    def __init__(self, path: Path, manifest: Path | None = None):
        sheet = QPixmap(str(path))
        if sheet.isNull() or (sheet.width(), sheet.height()) != ATLAS_SIZE:
            raise ValueError(f"奶娃动画素材缺失或尺寸错误：{path}")
        self.frames = {
            name: [sheet.copy(col * FRAME_WIDTH, clip.row * FRAME_HEIGHT, FRAME_WIDTH, FRAME_HEIGHT)
                   for col in range(clip.count)]
            for name, clip in CLIPS.items()
        }
        self.look = [sheet.copy((i % 8) * FRAME_WIDTH, (9 + i // 8) * FRAME_HEIGHT,
                                FRAME_WIDTH, FRAME_HEIGHT) for i in range(16)]
        self.clips = dict(CLIPS)
        self.custom_actions = {}
        for name, action in load_custom_actions(manifest or path.parent.parent / "actions" / "manifest.json").items():
            custom_sheet = QPixmap(str(action.sheet))
            if custom_sheet.isNull() or (custom_sheet.width(), custom_sheet.height()) != (action.width * action.clip.count, action.height):
                logging.warning("Ignoring missing or incorrectly sized action sheet: %s", action.sheet)
                continue
            frames = []
            for column in range(action.clip.count):
                source = custom_sheet.copy(column * action.width, 0, action.width, action.height)
                # All animations share the pet's canvas and its baseline, even when
                # an imported animation was exported at a different resolution.
                if (action.width, action.height) != (FRAME_WIDTH, FRAME_HEIGHT):
                    source = source.scaled(FRAME_WIDTH, FRAME_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                    canvas = QPixmap(FRAME_WIDTH, FRAME_HEIGHT)
                    canvas.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(canvas)
                    painter.drawPixmap((FRAME_WIDTH - source.width()) // 2, FRAME_HEIGHT - source.height(), source)
                    painter.end()
                    source = canvas
                frames.append(source)
            self.frames[name] = frames
            self.clips[name] = action.clip
            self.custom_actions[name] = action
        self.cache: dict[tuple[str, int, int], QPixmap] = {}
        self.masks: dict[tuple[str, int, int], QRegion] = {}

    def frame(self, action: str, index: int, size: int) -> QPixmap:
        key = (action, index, size)
        if key not in self.cache:
            source = self.look[index] if action == "look" else self.frames[action][index]
            self.cache[key] = source.scaled(round(FRAME_WIDTH * size / 100), round(FRAME_HEIGHT * size / 100),
                                            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return self.cache[key]

    def mask(self, action: str, index: int, size: int) -> QRegion:
        key = (action, index, size)
        if key not in self.masks:
            self.masks[key] = QRegion(self.frame(action, index, size).mask())
        return self.masks[key]

    def clear_scaled(self):
        self.cache.clear()
        self.masks.clear()


class PetWindow(QWidget):
    BUBBLE_HEIGHT = 74
    AUTO_SLEEP_SECONDS = 10 * 60

    def __init__(self, assets: Path, config_path: Path, *, enable_tray: bool = True):
        super().__init__()
        self.config_path = config_path
        self.assets = assets
        self.preferences = Preferences.load(config_path)
        self.atlas = SpriteAtlas(assets / "naifrog" / "spritesheet.webp")
        self.clips = self.atlas.clips
        self.custom_actions = self.atlas.custom_actions
        self.drag_action = next((name for name, action in self.custom_actions.items()
                                 if action.trigger == "drag"), None)
        self.sleep_action = next((name for name, action in self.custom_actions.items()
                                  if action.trigger == "sleep"), None)
        self.app_icon = QIcon(str(assets / "icon.ico"))
        if self.app_icon.isNull():
            self.app_icon = QIcon(self.atlas.frames["idle"][0])
        self.setWindowIcon(self.app_icon)
        self.setWindowTitle("奶娃桌宠")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self._apply_flags()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.action = "wave"
        self.action_started = time.monotonic()
        self.last_interaction = self.action_started
        self.sleeping = False
        self._press_woke_sleep = False
        self.action_until = self.action_started + 2.4
        self.next_roam = self.action_started + 18
        self.next_custom_action = self.action_started + random.uniform(12, 25)
        self.last_custom_action: str | None = None
        self.walk_until = 0.0
        self.direction = 1
        self.position_x = 0.0
        self.paused = False
        self.pause_started = 0.0
        self.drag_anchor: QPoint | None = None
        self.press_position: QPoint | None = None
        self.dragging = False
        self._drag_animation_active = False
        self._mouse_interaction = 0
        self.last_hover = 0.0
        self.menu_open = False
        self.bubble_text = ""
        self.bubble_until = 0.0
        self._display_key = None
        self._last_tick = time.monotonic()
        self._last_settings_save = self._last_tick
        self.panel: HomePanel | None = None
        self.tray: QSystemTrayIcon | None = None
        self._resize_pet()
        self._restore_position()
        self.position_x = float(self.x())
        self._build_menu()
        if enable_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.app_icon, self)
            self.tray.setToolTip("奶娃桌宠 · 双击打开小窝")
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)
        QApplication.instance().screenAdded.connect(self._screen_added)
        QApplication.instance().screenRemoved.connect(self._screens_changed)
        for screen in QApplication.screens():
            screen.availableGeometryChanged.connect(self._screens_changed)
        self.say("我来啦！右键打开我的小窝。", 5)
        self._refresh_frame()

    def _apply_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.preferences.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _screen_added(self, screen):
        screen.availableGeometryChanged.connect(self._screens_changed)
        self._screens_changed()

    def _screens_changed(self, *_):
        self.move(self._clamped_position(self.pos()))
        self.position_x = float(self.x())
        self.save_preferences()

    def pet_rect(self) -> QRect:
        width = round(FRAME_WIDTH * self.preferences.size / 100)
        height = round(FRAME_HEIGHT * self.preferences.size / 100)
        return QRect((self.width() - width) // 2, self.BUBBLE_HEIGHT, width, height)

    def bubble_rect(self) -> QRect:
        return QRect(12, 8, self.width() - 24, 49)

    def _resize_pet(self):
        self.setFixedSize(max(256, round(FRAME_WIDTH * self.preferences.size / 100) + 24),
                          round(FRAME_HEIGHT * self.preferences.size / 100) + self.BUBBLE_HEIGHT + 6)

    def _restore_position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        if self.preferences.x is None or self.preferences.y is None:
            desired = QPoint(screen.right() - self.width() - 40, screen.bottom() - self.height() - 12)
        else:
            desired = QPoint(self.preferences.x, self.preferences.y)
        self.move(self._clamped_position(desired))

    def _clamped_position(self, point: QPoint) -> QPoint:
        center = point + self.rect().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = min(QApplication.screens(), key=lambda item:
                         (item.availableGeometry().center().x() - center.x()) ** 2 +
                         (item.availableGeometry().center().y() - center.y()) ** 2)
        area = screen.availableGeometry()
        return QPoint(clamp(point.x(), area.left(), area.right() - self.width() + 1),
                      clamp(point.y(), area.top(), area.bottom() - self.height() + 1))

    def _build_menu(self):
        self.menu = QMenu()
        self.menu.setStyleSheet("QMenu { background: #fffdf6; color: #4f4837; padding: 7px; border: 1px solid #dfd8c7; }"
                                "QMenu::item { padding: 8px 25px 8px 14px; border-radius: 5px; }"
                                "QMenu::item:selected { background: #f9eab6; }"
                                "QMenu::separator { height: 1px; background: #e9e3d4; margin: 5px; }")
        self.menu.addAction("奶娃的小窝…", self.open_panel)
        self.menu.addSeparator()
        for action, (label, _) in ACTION_TEXT.items():
            self.menu.addAction(label, lambda checked=False, name=action: self.play(name))
        if self.custom_actions:
            self.menu.addSeparator()
            for action, metadata in self.custom_actions.items():
                if metadata.trigger is None:
                    self.menu.addAction(metadata.clip.label, lambda checked=False, name=action: self.play(name))
        self.sleep_menu_action = self.menu.addAction("睡觉", self.toggle_sleep)
        self.sleep_menu_action.setEnabled(self.sleep_action is not None)
        self.menu.addSeparator()
        self.walk_action = QAction("自由散步", self.menu, checkable=True)
        self.walk_action.setChecked(self.preferences.auto_walk)
        self.walk_action.triggered.connect(lambda enabled: self.set_preference("auto_walk", enabled))
        self.menu.addAction(self.walk_action)
        self.auto_actions_action = QAction("随机播放新动作", self.menu, checkable=True)
        self.auto_actions_action.setChecked(self.preferences.auto_actions)
        self.auto_actions_action.setEnabled(bool(self.custom_actions))
        self.auto_actions_action.triggered.connect(lambda enabled: self.set_preference("auto_actions", enabled))
        self.menu.addAction(self.auto_actions_action)
        self.auto_sleep_action = QAction("10 分钟不互动后自动睡觉", self.menu, checkable=True)
        self.auto_sleep_action.setChecked(self.preferences.auto_sleep)
        self.auto_sleep_action.setEnabled(self.sleep_action is not None)
        self.auto_sleep_action.triggered.connect(lambda enabled: self.set_preference("auto_sleep", enabled))
        self.menu.addAction(self.auto_sleep_action)
        self.pause_action = self.menu.addAction("暂停陪伴", self.toggle_pause)
        self.menu.addAction("回到屏幕右下角", self.reset_position)
        if self.tray is not None or QSystemTrayIcon.isSystemTrayAvailable():
            self.visibility_action = self.menu.addAction("暂时藏起来", self.toggle_visibility)
        else:
            self.visibility_action = None
        self.menu.addSeparator()
        self.menu.addAction("关于奶娃", self.show_about)
        self.menu.addAction("退出奶娃", self.quit_pet)
        self.menu.aboutToShow.connect(self._menu_started)
        self.menu.aboutToHide.connect(self._menu_finished)

    def _menu_started(self):
        self.last_interaction = time.monotonic()
        self.menu_open = True
        self._stop_walking()
        self.walk_action.setChecked(self.preferences.auto_walk)
        self.auto_actions_action.setChecked(self.preferences.auto_actions)
        self.auto_sleep_action.setChecked(self.preferences.auto_sleep)
        self.sleep_menu_action.setText("唤醒奶娃" if self.sleeping else "睡觉")
        self.pause_action.setText("继续陪伴" if self.paused else "暂停陪伴")
        if self.visibility_action:
            self.visibility_action.setText("叫奶娃出来" if not self.isVisible() else "暂时藏起来")

    def _menu_finished(self):
        self.menu_open = False
        now = time.monotonic()
        self.last_interaction = now
        self.next_roam = now + 15
        self._schedule_custom_action(now)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_pet()
            self.open_panel()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_pet()

    def open_panel(self):
        self.last_interaction = time.monotonic()
        self._stop_walking()
        if self.panel is None:
            self.panel = HomePanel(self)
        self.panel.sync()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def show_pet(self):
        was_visible = self.isVisible()
        self.move(self._clamped_position(self.pos()))
        self.position_x = float(self.x())
        self.show()
        self.raise_()
        self._last_tick = time.monotonic()
        if not was_visible:
            self.last_interaction = self._last_tick
            self.next_roam = self._last_tick + 15
            self._schedule_custom_action(self._last_tick)
        if not self.paused:
            self.timer.start(self._animation_interval())
        self._refresh_frame()

    def toggle_visibility(self):
        if self.isVisible():
            if not self.tray:
                return
            self._stop_walking()
            self.hide()
            self.timer.stop()
            self.save_preferences()
        else:
            self.show_pet()

    def set_preference(self, name: str, value):
        self.last_interaction = time.monotonic()
        setattr(self.preferences, name, value)
        if name == "size":
            old_bottom = self.geometry().bottom()
            old_center = self.geometry().center().x()
            self.atlas.clear_scaled()
            self._resize_pet()
            self.move(self._clamped_position(QPoint(old_center - self.width() // 2, old_bottom - self.height() + 1)))
            self.position_x = float(self.x())
        elif name == "always_on_top":
            visible = self.isVisible()
            position = self.pos()
            self._apply_flags()
            self.move(position)
            if visible:
                self.show()
        elif name == "auto_walk":
            self._stop_walking()
            self.next_roam = time.monotonic() + 3
            self.walk_action.setChecked(value)
        elif name == "auto_actions":
            self._schedule_custom_action(time.monotonic())
            self.auto_actions_action.setChecked(value)
        elif name == "auto_sleep":
            self.auto_sleep_action.setChecked(value)
        elif name == "speech" and not value:
            self.bubble_text = ""
        self._display_key = None
        self._refresh_frame()
        if self.panel and name in self.panel.checks:
            check = self.panel.checks[name]
            check.blockSignals(True)
            check.setChecked(bool(value))
            check.blockSignals(False)
        self.save_preferences()

    def save_preferences(self):
        self.preferences.x, self.preferences.y = self.x(), self.y()
        self.preferences.save(self.config_path)

    def say(self, text: str, duration=3.5):
        if self.preferences.speech:
            self.bubble_text = text
            self.bubble_until = time.monotonic() + duration
            self._display_key = None
            self.update()

    def _schedule_custom_action(self, now: float):
        self.next_custom_action = now + random.uniform(12, 25)

    def _animation_interval(self) -> int:
        if self.walk_until:
            return 33
        return min(100, max(16, round(1000 / self.clips[self.action].fps)))

    def _can_start_automatic(self) -> bool:
        return (self.isVisible() and not self.paused and not self.sleeping and self.drag_anchor is None
                and not self.menu_open and not (self.panel and self.panel.isVisible()))

    def sleep(self, *, automatic: bool = False) -> bool:
        if self.sleep_action is None or self.sleeping or self.drag_anchor is not None:
            return False
        if automatic and not self._can_start_automatic():
            return False
        if self.paused:
            self.toggle_pause()
        if not automatic:
            self.show_pet()
            self.last_interaction = time.monotonic()
        self._stop_walking()
        self.sleeping = True
        self.action = self.sleep_action
        self.action_started = time.monotonic()
        self.action_until = float("inf")
        self.bubble_text = ""
        self._display_key = None
        self.timer.start(self._animation_interval())
        self._refresh_frame()
        self._sync_status()
        logging.info("Pet fell asleep: automatic=%s", automatic)
        return True

    def wake(self, *, speak: bool = True) -> bool:
        if not self.sleeping:
            return False
        now = time.monotonic()
        self.sleeping = False
        self.action = "idle"
        self.action_started = now
        self.action_until = 0
        self.walk_until = 0
        self.last_interaction = now
        self.next_roam = now + 15
        self._schedule_custom_action(now)
        self._last_tick = now
        if self.paused:
            self.pause_started = now
        elif self.isVisible():
            self.timer.start(self._animation_interval())
        if speak:
            self.say("睡醒啦，继续陪你！")
        self._display_key = None
        self._refresh_frame()
        self._sync_status()
        logging.info("Pet woke up")
        return True

    def toggle_sleep(self):
        if self.sleeping:
            self.wake()
        else:
            self.sleep()

    def _start_random_action(self, now: float) -> bool:
        if not self._can_start_automatic() or self.action != "idle" or self.walk_until:
            return False
        candidates = [name for name, action in self.custom_actions.items()
                      if action.random and action.trigger != "drag"]
        if len(candidates) > 1:
            candidates = [name for name in candidates if name != self.last_custom_action]
        if not candidates:
            self._schedule_custom_action(now)
            return False
        self.play(random.choice(candidates), speak=False, automatic=True)
        return True

    def play(self, action: str, *, speak: bool = True, automatic: bool = False):
        if action == self.sleep_action and self.sleep_action is not None:
            return self.sleep(automatic=automatic)
        if action not in self.clips or self.dragging:
            return
        if automatic and (not self._can_start_automatic() or self.action != "idle" or self.walk_until):
            return
        if not automatic:
            self.wake(speak=False)
            self.last_interaction = time.monotonic()
        if self.paused:
            self.toggle_pause()
        if not automatic:
            self.show_pet()
        self.walk_until = 0
        self.action = action
        self.action_started = time.monotonic()
        clip = self.clips[action]
        custom = self.custom_actions.get(action)
        duration = clip.count / clip.fps * custom.loops if custom else max(2.5, clip.count / clip.fps * 3)
        self.action_until = self.action_started + duration
        # Automatic behaviours keep the other behaviour's pending deadline;
        # repeatedly rescheduling it here can otherwise postpone it forever.
        if not automatic:
            self.next_roam = self.action_until + 12
        self._schedule_custom_action(self.action_until)
        self.timer.setInterval(self._animation_interval())
        if custom:
            self.last_custom_action = action
            logging.info("Playing custom action: id=%s automatic=%s", action, automatic)
        if speak and action in ACTION_TEXT:
            self.say(ACTION_TEXT[action][1])
        if action == "relax":
            self.bubble_text = ""
        self._refresh_frame()
        self._sync_status()

    def toggle_pause(self):
        now = time.monotonic()
        self.last_interaction = now
        if self._drag_animation_active:
            # A deliberate drag keeps playing even when companionship is paused.
            # The switch still determines whether animation resumes on release.
            self.paused = not self.paused
            self.pause_started = now
            self.bubble_text = ""
            self._sync_status()
            return
        if self.paused:
            delta = now - self.pause_started
            self.action_started += delta
            self.action_until += delta
            self.next_roam = now + 10
            self._schedule_custom_action(now)
            self._last_tick = now
            self.paused = False
            if self.isVisible():
                self.timer.start(self._animation_interval())
        else:
            self._stop_walking()
            self.paused = True
            self.pause_started = now
            self.bubble_text = ""
            self.timer.stop()
        self._display_key = None
        self._refresh_frame()
        self._sync_status()

    def _stop_walking(self):
        if self.walk_until:
            self.walk_until = 0
            self.action = "idle"
            self.action_started = time.monotonic()
            self.action_until = 0
            self.timer.setInterval(100)
            self.save_preferences()
            self._sync_status()

    def _start_walk(self, now: float):
        if self.sleeping:
            return
        self.direction = random.choice((-1, 1))
        self.position_x = float(self.x())
        self.walk_until = now + random.uniform(2.8, 5)
        self.action = "walk_right" if self.direction == 1 else "walk_left"
        self.action_started = now
        self.action_until = self.walk_until
        self.timer.setInterval(33)
        self._sync_status()

    def _tick(self):
        now = time.monotonic()
        delta = min(now - self._last_tick, 0.1)
        self._last_tick = now
        if self.drag_anchor is not None:
            if not QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
                self._finish_mouse_interaction(cancelled=True)
            else:
                if self.bubble_text and now >= self.bubble_until:
                    self.bubble_text = ""
                    self._display_key = None
                if self._drag_animation_active:
                    self._refresh_frame()
            return
        if self.paused or self.menu_open or not self.isVisible():
            return
        if self.bubble_text and now >= self.bubble_until:
            self.bubble_text = ""
            self._display_key = None
        if (not self.sleeping and self.sleep_action is not None and self.preferences.auto_sleep
                and now - self.last_interaction >= self.AUTO_SLEEP_SECONDS and self._can_start_automatic()):
            self.sleep(automatic=True)
        if self.sleeping:
            self._refresh_frame()
            return
        if self.walk_until:
            if now >= self.walk_until:
                self._stop_walking()
                self.next_roam = now + random.uniform(18, 35)
                self.timer.setInterval(100)
            else:
                speed = 38 * self.preferences.size / 100
                self.position_x += self.direction * speed * delta
                desired = QPoint(round(self.position_x), self.y())
                bounded = self._clamped_position(desired)
                if desired.x() != bounded.x():
                    self.direction *= -1
                    self.position_x = float(bounded.x())
                    self.action = "walk_right" if self.direction == 1 else "walk_left"
                self.move(bounded)
        elif self.action != "idle" and now >= self.action_until:
            self.action = "idle"
            self.action_started = now
            self.timer.setInterval(100)
            self._schedule_custom_action(now)
            self._sync_status()
        elif self.action == "idle" and self._can_start_automatic():
            if self.preferences.auto_actions and now >= self.next_custom_action:
                self._start_random_action(now)
            if self.action == "idle" and now >= self.next_roam and self.preferences.auto_walk:
                self._start_walk(now)
        if now - self._last_settings_save >= 15:
            self.save_preferences()
            self._last_settings_save = now
        self._refresh_frame()

    def _current_frame(self):
        now = self.pause_started if self.paused and not self._drag_animation_active else time.monotonic()
        index = frame_at(self.action, now - self.action_started, self.clips)
        action = self.action
        if (action == "idle" and self.preferences.follow_cursor and not self.paused
                and (now - self.action_started) % 4 < 1.3):
            center = self.mapToGlobal(self.pet_rect().center())
            cursor = QCursor.pos()
            dx, dy = cursor.x() - center.x(), cursor.y() - center.y()
            if math.hypot(dx, dy) < 700:
                action, index = "look", look_direction(dx, dy)
        return action, index

    def _refresh_frame(self):
        action, index = self._current_frame()
        key = (action, index, self.preferences.size, bool(self.bubble_text))
        if key != self._display_key:
            self._display_key = key
            pet = self.pet_rect()
            region = self.atlas.mask(action, index, self.preferences.size).translated(pet.topLeft())
            if self.bubble_text:
                region = region.united(QRegion(self.bubble_rect().adjusted(-2, -2, 2, 9)))
            self.setMask(region)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        action, index = self._current_frame()
        painter.drawPixmap(self.pet_rect().topLeft(), self.atlas.frame(action, index, self.preferences.size))
        if self.bubble_text:
            rect = QRectF(self.bubble_rect())
            path = QPainterPath()
            path.addRoundedRect(rect, 15, 15)
            cx = rect.center().x()
            path.moveTo(cx - 7, rect.bottom() - 1)
            path.lineTo(cx, rect.bottom() + 7)
            path.lineTo(cx + 7, rect.bottom() - 1)
            path.closeSubpath()
            painter.fillPath(path, QColor("#fffcf1"))
            painter.setPen(QColor("#615337"))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(rect.adjusted(12, 4, -12, -4), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.bubble_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.drag_anchor is not None:
                self._finish_mouse_interaction(cancelled=True)
            self._press_woke_sleep = self.sleeping
            self.wake(speak=False)
            self.last_interaction = time.monotonic()
            self._stop_walking()
            self._mouse_interaction += 1
            self.press_position = event.globalPosition().toPoint()
            self.drag_anchor = self.press_position - self.pos()
            self.dragging = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            # Keep a release watchdog even if the pet was paused before pressing.
            self.timer.start(self._animation_interval())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_anchor is not None:
            if not event.buttons() & Qt.MouseButton.LeftButton:
                self._finish_mouse_interaction(cancelled=True)
                event.accept()
                return
            point = event.globalPosition().toPoint()
            if not self.dragging and (point - self.press_position).manhattanLength() > QApplication.startDragDistance():
                self._begin_drag()
            if self.dragging:
                self.move(self._clamped_position(point - self.drag_anchor))
                self.position_x = float(self.x())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_anchor is not None:
            # A distant release is not a click, even if Windows coalesced or
            # lost the mouse-move event during the interaction.
            distant_release = (not self.dragging and self.press_position is not None
                               and (event.globalPosition().toPoint() - self.press_position).manhattanLength()
                               > QApplication.startDragDistance())
            self._finish_mouse_interaction(cancelled=distant_release)
            event.accept()

    def _begin_drag(self):
        self.dragging = True
        self._drag_animation_active = self.drag_action is not None
        now = time.monotonic()
        if self._drag_animation_active:
            self.walk_until = 0
            self.action = self.drag_action
            self.action_started = now
            self.action_until = float("inf")
            self.bubble_text = ""
            self._display_key = None
            self.timer.start(self._animation_interval())
            self._refresh_frame()
            self._sync_status()
        logging.info("Drag started: action=%s paused=%s", self.drag_action, self.paused)

    def _finish_mouse_interaction(self, *, cancelled=False):
        if self.drag_anchor is None:
            return
        dragged = self.dragging
        animated = self._drag_animation_active
        woke_sleep = self._press_woke_sleep
        self._press_woke_sleep = False
        self.drag_anchor = None
        self.press_position = None
        self.dragging = False
        self._drag_animation_active = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        now = time.monotonic()
        self.last_interaction = now
        self._last_tick = now
        self.position_x = float(self.x())
        self.save_preferences()
        self.next_roam = now + 15
        self._schedule_custom_action(now)
        if animated:
            self.action = "idle"
            self.action_started = now
            self.action_until = 0
            self.pause_started = now if self.paused else self.pause_started
        if self.paused or not self.isVisible():
            self.timer.stop()
        else:
            self.timer.start(self._animation_interval())
        if not dragged and not cancelled:
            if woke_sleep:
                self.say("睡醒啦，继续陪你！")
            else:
                self.play("laugh")
        elif dragged and not self.paused and not cancelled:
            if not animated:
                self.play("wave", speak=False)
            self.say("搬个新位置，继续陪你。", 2)
        self._display_key = None
        self._refresh_frame()
        self._sync_status()
        if dragged:
            logging.info("Drag ended: action=%s cancelled=%s paused=%s", self.drag_action, cancelled, self.paused)

    def _open_chatgpt(self):
        self.last_interaction = time.monotonic()
        try:
            open_chatgpt()
            message = "已用谷歌浏览器打开 ChatGPT。"
            logging.info("Opened ChatGPT in Google Chrome from home panel")
        except OSError:
            logging.exception("Cannot open ChatGPT in Google Chrome")
            message = "没有打开谷歌浏览器，请检查 Chrome 是否安装。"
        if self.panel:
            self.panel.chatgpt_status.setText(message)

    def _cancel_mouse_interaction(self, interaction: int):
        if self._mouse_interaction == interaction:
            self._finish_mouse_interaction(cancelled=True)

    def event(self, event):
        if getattr(self, "drag_anchor", None) is not None:
            if event.type() == QEvent.Type.UngrabMouse:
                # Qt can notify capture loss just before delivering the normal
                # release. Let that handler run first, preserving single clicks.
                interaction = self._mouse_interaction
                QTimer.singleShot(0, lambda: self._cancel_mouse_interaction(interaction))
            elif event.type() in (QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
                self._finish_mouse_interaction(cancelled=True)
        return super().event(event)

    def enterEvent(self, event):
        now = time.monotonic()
        if not self.paused and self.drag_anchor is None and not self.menu_open and now - self.last_hover > 8:
            self.last_hover = now
            if self.action == "idle":
                self.play("laugh", speak=False)
        super().enterEvent(event)

    def contextMenuEvent(self, event):
        self.menu.popup(event.globalPos())
        event.accept()

    def wheelEvent(self, event):
        if event.angleDelta().y():
            step = 5 if event.angleDelta().y() > 0 else -5
            self.set_preference("size", clamp(self.preferences.size + step, 60, 180))
            if self.panel:
                self.panel.sync()
        event.accept()

    def reset_position(self):
        self.last_interaction = time.monotonic()
        area = QApplication.primaryScreen().availableGeometry()
        self._stop_walking()
        self.move(self._clamped_position(QPoint(area.right() - self.width() - 35,
                                                area.bottom() - self.height() - 8)))
        self.position_x = float(self.x())
        self.show_pet()
        self.save_preferences()

    def _sync_status(self):
        if self.panel:
            self.panel.sync_status()

    def show_about(self):
        box = QMessageBox(self.panel if self.panel and self.panel.isVisible() else self)
        box.setWindowTitle("关于奶娃桌宠")
        box.setWindowIcon(self.app_icon)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText("创作者：菠萝吹徽")
        box.exec()

    def quit_pet(self):
        self.save_preferences()
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.save_preferences()
        if self.tray:
            self.hide()
            self.timer.stop()
            event.ignore()
        else:
            event.accept()
            QApplication.instance().quit()


class HomePanel(QDialog):
    def __init__(self, pet: PetWindow):
        super().__init__()
        self.pet = pet
        self.setWindowTitle("奶娃的小窝")
        self.setWindowIcon(pet.app_icon)
        self.setMinimumWidth(460)
        check_path = (pet.assets / "check.svg").as_posix()
        self.setStyleSheet(PANEL_STYLE + f'QCheckBox::indicator:checked {{ image: url("{check_path}"); }}')
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 19)
        root.setSpacing(17)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        eyebrow = QLabel("NAIWA  /  DESKTOP COMPANION")
        eyebrow.setObjectName("eyebrow")
        titles.addWidget(eyebrow)
        heading = QLabel("今天也陪你一起摸鱼")
        heading.setObjectName("heading")
        titles.addWidget(heading)
        subtitle = QLabel(f"一只奶娃，一点好心情。 · {APP_VERSION}")
        subtitle.setObjectName("muted")
        titles.addWidget(subtitle)
        titles.setSpacing(7)
        header.addLayout(titles, 1)
        portrait = QLabel()
        portrait.setPixmap(pet.atlas.frames["wave"][1].scaled(78, 85, Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation))
        header.addWidget(portrait)
        root.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        actions_layout = QVBoxLayout(card)
        actions_layout.setContentsMargins(17, 16, 17, 17)
        actions_layout.setSpacing(13)
        row = QHBoxLayout()
        label = QLabel("和奶娃玩一会儿")
        label.setObjectName("section")
        row.addWidget(label)
        row.addStretch()
        self.status = QLabel()
        self.status.setObjectName("badge")
        row.addWidget(self.status)
        actions_layout.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(9)
        actions = [(action, text) for action, (text, _) in ACTION_TEXT.items()]
        actions.extend((action, metadata.clip.label) for action, metadata in pet.custom_actions.items()
                       if metadata.trigger is None)
        self.action_buttons: dict[str, QPushButton] = {}
        for i, (action, text) in enumerate(actions):
            button = QPushButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, name=action: pet.play(name))
            self.action_buttons[action] = button
            grid.addWidget(button, i // 3, i % 3)
        self.sleep_button = QPushButton("睡觉")
        self.sleep_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sleep_button.setEnabled(pet.sleep_action is not None)
        self.sleep_button.clicked.connect(pet.toggle_sleep)
        self.chatgpt_button = QPushButton("打开 ChatGPT")
        self.chatgpt_button.setObjectName("primary")
        self.chatgpt_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chatgpt_button.setToolTip("使用谷歌 Chrome 打开 ChatGPT")
        self.chatgpt_button.clicked.connect(pet._open_chatgpt)
        grid.addWidget(self.chatgpt_button, (len(actions) + 2) // 3, 0, 1, 3)
        actions_layout.addLayout(grid)
        self.chatgpt_status = QLabel("ChatGPT 会在谷歌浏览器中打开。")
        self.chatgpt_status.setObjectName("muted")
        self.chatgpt_status.setWordWrap(True)
        actions_layout.addWidget(self.chatgpt_status)
        root.addWidget(card)

        settings = QFrame()
        settings.setObjectName("card")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(17, 16, 17, 16)
        settings_layout.setSpacing(12)
        size_row = QHBoxLayout()
        label = QLabel("奶娃的大小")
        label.setObjectName("section")
        size_row.addWidget(label)
        size_row.addStretch()
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        size_row.addWidget(self.size_label)
        settings_layout.addLayout(size_row)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(60, 180)
        self.slider.setSingleStep(5)
        self.slider.valueChanged.connect(self._size_changed)
        settings_layout.addWidget(self.slider)
        toggles = QGridLayout()
        self.checks: dict[str, QCheckBox] = {}
        for i, (name, text) in enumerate([
            ("auto_walk", "在桌面自由散步"), ("auto_actions", "随机播放新动作"),
            ("follow_cursor", "好奇地看向鼠标"),
            ("always_on_top", "一直待在最上面"), ("speech", "偶尔说句悄悄话"),
            ("auto_sleep", "10 分钟不互动后自动睡觉"),
        ]):
            check = QCheckBox(text)
            check.toggled.connect(lambda enabled, key=name: pet.set_preference(key, enabled))
            self.checks[name] = check
            if name == "auto_sleep":
                check.setEnabled(pet.sleep_action is not None)
            toggles.addWidget(check, i // 2, i % 2)
        self.startup_button = QPushButton()
        self.startup_button.setObjectName("autostart")
        self.startup_button.setCheckable(True)
        self.startup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.startup_button.setToolTip("开启后，登录 Windows 时自动显示奶娃。")
        self.startup_button.clicked.connect(self._toggle_autostart)
        toggles.addWidget(self.startup_button, 3, 0, 1, 2)
        settings_layout.addLayout(toggles)
        self.startup_error = QLabel()
        self.startup_error.setObjectName("muted")
        self.startup_error.setWordWrap(True)
        self.startup_error.hide()
        settings_layout.addWidget(self.startup_error)
        root.addWidget(settings)

        drag_help = pet.custom_actions[pet.drag_action].clip.label if pet.drag_action else "搬家"
        help_label = QLabel(f"轻点：大笑／唤醒  ·  拖动：{drag_help}\n睡觉时会暂停散步，轻点或拖动就能叫醒。")
        help_label.setObjectName("muted")
        help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(help_label)
        footer = QHBoxLayout()
        self.pause_button = QPushButton("暂停陪伴")
        self.pause_button.clicked.connect(pet.toggle_pause)
        footer.addWidget(self.pause_button)
        footer.addWidget(self.sleep_button)
        find_button = QPushButton("把奶娃叫回来")
        find_button.setObjectName("primary")
        find_button.clicked.connect(pet.reset_position)
        footer.addWidget(find_button, 1)
        root.addLayout(footer)
        about = QPushButton("创作者：菠萝吹徽")
        about.setObjectName("quiet")
        about.clicked.connect(pet.show_about)
        root.addWidget(about, alignment=Qt.AlignmentFlag.AlignCenter)
        self.sync()

    def _sync_autostart(self):
        try:
            enabled = is_autostart_enabled()
        except OSError:
            logging.exception("Cannot read Windows startup setting")
            self.startup_button.setEnabled(False)
            self.startup_button.setText("开机自启动：读取失败")
            self.startup_error.setText("无法读取自启动设置，请重新打开小窝重试。")
            self.startup_error.show()
            return
        self.startup_button.blockSignals(True)
        self.startup_button.setChecked(enabled)
        self.startup_button.setText("开机自启动：已开启" if enabled else "开机自启动：已关闭")
        self.startup_button.setEnabled(True)
        self.startup_button.blockSignals(False)
        self.startup_error.clear()
        self.startup_error.hide()

    def _toggle_autostart(self, enabled):
        try:
            set_autostart_enabled(enabled)
            if is_autostart_enabled() != enabled:
                raise OSError("Windows startup state did not match the requested value")
        except OSError:
            logging.exception("Cannot change Windows startup setting")
            self._sync_autostart()
            self.startup_error.setText("自启动设置失败，请重新打开小窝后再试。")
            self.startup_error.show()
            return
        self._sync_autostart()
        logging.info("Windows login startup changed: enabled=%s", enabled)

    def _size_changed(self, value):
        self.size_label.setText(f"{value}%")
        self.pet.set_preference("size", value)

    def sync_status(self):
        resting = self.pet.paused and not self.pet._drag_animation_active
        self.status.setText("已暂停" if resting else "睡觉中" if self.pet.sleeping
                            else self.pet.clips[self.pet.action].label + "中")
        self.sleep_button.setText("唤醒奶娃" if self.pet.sleeping else "睡觉")
        self.pet.sleep_menu_action.setText("唤醒奶娃" if self.pet.sleeping else "睡觉")
        self.pause_button.setText("继续陪伴" if self.pet.paused else "暂停陪伴")

    def sync(self):
        self.slider.blockSignals(True)
        self.slider.setValue(self.pet.preferences.size)
        self.slider.blockSignals(False)
        self.size_label.setText(f"{self.pet.preferences.size}%")
        for name, check in self.checks.items():
            check.blockSignals(True)
            check.setChecked(getattr(self.pet.preferences, name))
            check.blockSignals(False)
        self._sync_autostart()
        self.sync_status()

    def closeEvent(self, event):
        now = time.monotonic()
        self.pet.last_interaction = now
        self.pet.next_roam = now + 15
        self.pet._schedule_custom_action(now)
        self.pet.save_preferences()
        event.accept()
