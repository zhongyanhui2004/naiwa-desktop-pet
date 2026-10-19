"""Animation metadata and preferences, independent of the desktop UI."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import logging
import math
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Clip:
    row: int
    count: int
    fps: float
    label: str


# Counts come from the upstream README, rather than the empty cells in the atlas.
CLIPS = {
    "idle": Clip(0, 6, 6, "发呆"),
    "walk_right": Clip(1, 8, 10, "向右散步"),
    "walk_left": Clip(2, 8, 10, "向左散步"),
    "wave": Clip(3, 4, 5, "打招呼"),
    "laugh": Clip(4, 5, 7, "开怀大笑"),
    "sad": Clip(5, 8, 6, "委屈一下"),
    "wait": Clip(6, 6, 6, "左顾右盼"),
    "work": Clip(7, 6, 7, "认真工作"),
    "think": Clip(8, 6, 6, "抱胸思考"),
}
FRAME_WIDTH, FRAME_HEIGHT = 192, 208
ATLAS_SIZE = (1536, 2288)


@dataclass(frozen=True)
class CustomAction:
    """One optional animation imported alongside the original sprite atlas."""

    sheet: Path
    width: int
    height: int
    clip: Clip
    loops: int = 2
    random: bool = True
    trigger: str | None = None


def load_custom_actions(manifest: Path) -> dict[str, CustomAction]:
    """Read optional action metadata, ignoring malformed entries independently."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("actions"), list):
            raise ValueError("Unsupported action manifest")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        logging.warning("Cannot read custom action manifest: %s", manifest, exc_info=True)
        return {}

    actions = {}
    folder = manifest.parent.resolve()
    for entry in data["actions"]:
        try:
            if not isinstance(entry, dict):
                raise ValueError("Action must be an object")
            name, label = entry["id"], entry["name"]
            if (not isinstance(name, str) or not name or name in CLIPS or name == "look"
                    or name in actions or not isinstance(label, str) or not label.strip()):
                raise ValueError("Invalid or duplicate action name")
            dimensions = [entry["frame_width"], entry["frame_height"], entry["frame_count"]]
            if any(type(value) is not int or value <= 0 for value in dimensions):
                raise ValueError("Invalid frame dimensions or count")
            width, height, count = dimensions
            if width > 2048 or height > 2048 or count > 1000 or width * height * count > 64_000_000:
                raise ValueError("Action sheet is too large")
            fps, loops, automatic = entry["fps"], entry.get("loops", 2), entry.get("random", True)
            if (type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 60
                    or type(loops) is not int or not 1 <= loops <= 20 or type(automatic) is not bool):
                raise ValueError("Invalid playback settings")
            trigger = entry.get("trigger")
            if trigger not in (None, "drag", "sleep"):
                raise ValueError("Invalid action trigger")
            if not isinstance(entry["sheet"], str):
                raise ValueError("Invalid sheet filename")
            sheet = (folder / entry["sheet"]).resolve()
            if not sheet.is_relative_to(folder) or sheet == folder:
                raise ValueError("Action sheet must be inside its asset folder")
            actions[name] = CustomAction(sheet, width, height, Clip(0, count, fps, label.strip()),
                                         loops, automatic and trigger is None, trigger)
        except (KeyError, OSError, ValueError, TypeError):
            logging.warning("Ignoring invalid custom action entry in %s: %r", manifest, entry)
    return actions


def frame_at(action: str, elapsed: float, clips: Mapping[str, Clip] | None = None) -> int:
    clip = (CLIPS if clips is None else clips)[action]
    return int(max(0.0, elapsed) * clip.fps) % clip.count


def look_direction(dx: float, dy: float) -> int:
    """16 clockwise directions, starting with up, as in atlas rows 9 and 10."""
    if dx == 0 and dy == 0:
        return 0
    return round((math.atan2(dy, dx) + math.pi / 2) * 8 / math.pi) % 16


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, max(minimum, maximum)))


@dataclass
class Preferences:
    size: int = 115
    x: int | None = None
    y: int | None = None
    auto_walk: bool = True
    auto_actions: bool = True
    auto_sleep: bool = True
    follow_cursor: bool = True
    always_on_top: bool = True
    speech: bool = True

    @classmethod
    def load(cls, path: Path) -> Preferences:
        preferences = cls()
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                return preferences
            for field in fields(cls):
                value = values.get(field.name)
                if field.name in {"x", "y"}:
                    if type(value) is int:
                        setattr(preferences, field.name, value)
                elif field.name == "size":
                    if type(value) is int:
                        preferences.size = clamp(value, 60, 180)
                elif type(value) is bool:
                    setattr(preferences, field.name, value)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logging.warning("Cannot read preferences; using defaults", exc_info=True)
        return preferences

    def save(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            logging.exception("Cannot save preferences")
