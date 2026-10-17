"""Prepare the supplied riding animation for the explicit drag interaction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
from PIL import Image, ImageDraw

from extract_recorded_actions import CANVAS, checker_preview, remove_connected_background


ROOT = Path(__file__).resolve().parents[1]
CROP = (0, 344, 592, 934)


def extract(source: Path, start: int, end: int | None):
    cap = cv2.VideoCapture(str(source))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not cap.isOpened() or fps <= 0:
        raise ValueError(f"Cannot read source recording: {source}")
    finish = total if end is None else min(end, total)
    if not 0 <= start < finish:
        raise ValueError("Invalid frame range")
    decoded = []
    for index in range(finish):
        success, frame = cap.read()
        if not success:
            raise ValueError(f"Missing source frame: {index}")
        if index >= start:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            x1, y1, x2, y2 = CROP
            crop = rgb[y1:y2, x1:x2]
            hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
            # The video has a baked checkerboard and a neutral border. Only
            # neutral pixels connected to the outer background are removed.
            decoded.append(remove_connected_background(crop, hsv[:, :, 1] < 65))
    cap.release()
    bounds = [frame.getbbox() for frame in decoded]
    common = (min(b[0] for b in bounds), min(b[1] for b in bounds),
              max(b[2] for b in bounds), max(b[3] for b in bounds))
    width, height = common[2] - common[0], common[3] - common[1]
    scale = min(178 / width, 186 / height)
    fitted = (round(width * scale), round(height * scale))
    frames = []
    for raw in decoded:
        sprite = raw.crop(common).resize(fitted, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", CANVAS)
        canvas.alpha_composite(sprite, ((CANVAS[0] - fitted[0]) // 2, CANVAS[1] - 8 - fitted[1]))
        frames.append(canvas)
    output = ROOT / "assets" / "actions"
    preview = ROOT / "artifacts" / "drag-preview"
    output.mkdir(parents=True, exist_ok=True)
    preview.mkdir(parents=True, exist_ok=True)
    strip = Image.new("RGBA", (CANVAS[0] * len(frames), CANVAS[1]))
    for index, frame in enumerate(frames):
        strip.paste(frame, (index * CANVAS[0], 0))
    strip.save(output / "q_drag.png", optimize=True)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["actions"] = [action for action in manifest["actions"] if action["id"] != "q_drag"]
    manifest["actions"].append({
        "id": "q_drag", "name": "骑狗兜风", "sheet": "q_drag.png",
        "frame_width": CANVAS[0], "frame_height": CANVAS[1], "frame_count": len(frames),
        "fps": fps, "loops": 1, "random": False, "trigger": "drag",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    provenance = {
        "source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_fps": fps, "source_frames": total, "crop": CROP,
        "source_start_frame": start, "source_end_frame_exclusive": finish,
        "processing": "Remove black letterboxing, edge-connected checker background and detached marks; retain the recorded riding motion on a fixed transparent canvas.",
    }
    (output / "q_drag_SOURCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    contact = Image.new("RGB", (CANVAS[0] * 6, CANVAS[1] + 24), "#f5f1e8")
    for column in range(6):
        index = round(column * (len(frames) - 1) / 5)
        contact.paste(checker_preview(frames[index]), (column * CANVAS[0], 0))
        ImageDraw.Draw(contact).text((column * CANVAS[0] + 8, CANVAS[1] + 5), f"source frame {index + start}", fill="#443c2d")
    contact.save(preview / "contact.png")
    frames[len(frames) // 2].save(preview / "q_drag.png")
    previews = [checker_preview(frame) for frame in frames]
    previews[0].save(preview / "q_drag.gif", save_all=True, append_images=previews[1:], duration=round(1000 / fps), loop=0)
    print(f"q_drag: {len(frames)} frames at {fps} fps, bounds={common}, fitted={fitted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    args = parser.parse_args()
    extract(args.source, args.start, args.end)
