"""Extract the two supplied sticker recordings into transparent sprite strips.

Run with the asset-processing Python (OpenCV, NumPy and Pillow required),
not the minimal desktop application's runtime environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
CANVAS = (192, 208)
REGIONS = {
    "q_wave": {"name": "摆摆手", "crop": (60, 32, 229, 195)},
    "q_wiggle": {"name": "扭扭肚子", "crop": (59, 214, 223, 385)},
}


def remove_connected_background(rgb: np.ndarray, neutral_mask: np.ndarray | None = None) -> Image.Image:
    """Remove only neutral background reachable from the crop's edge.

    The warm cream belly stays opaque even when it is pale. Dark eyes and
    brown hands are also retained. No frame synthesis or motion changes.
    """
    if neutral_mask is None:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        neutral = (hsv[:, :, 1] < 32) & (hsv[:, :, 2] > 145)
    else:
        neutral = neutral_mask
    count, labels = cv2.connectedComponents(neutral.astype(np.uint8), connectivity=8)
    boundary_labels = set(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])).tolist())
    boundary_labels.discard(0)
    background = np.isin(labels, list(boundary_labels))
    foreground = (~background).astype(np.uint8)
    count, components, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    if count < 2:
        raise ValueError("No character was found in a recording frame")
    # A single continuous sticker, without the recording border or compression specks.
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    foreground = (components == largest).astype(np.uint8)
    alpha = cv2.GaussianBlur(foreground.astype(np.float32), (3, 3), 0.45)
    alpha[alpha < 0.025] = 0
    alpha[alpha > 0.975] = 1
    # Remove the white matte at antialiased edges; leave opaque interior colors intact.
    colors = rgb.astype(np.float32)
    edge = (alpha > 0) & (alpha < 1)
    a = np.maximum(alpha[edge, None], 0.08)
    colors[edge] = (colors[edge] - 250 * (1 - a)) / a
    rgba = np.dstack((np.clip(colors, 0, 255).astype(np.uint8), np.round(alpha * 255).astype(np.uint8)))
    rgba[rgba[:, :, 3] == 0, :3] = 0
    return Image.fromarray(rgba)


def checker_preview(frame: Image.Image) -> Image.Image:
    background = Image.new("RGB", CANVAS, "#dbe3ec")
    draw = ImageDraw.Draw(background)
    for y in range(0, CANVAS[1], 12):
        for x in range(0, CANVAS[0], 12):
            if (x // 12 + y // 12) % 2:
                draw.rectangle((x, y, x + 11, y + 11), fill="#f1f4f8")
    background.paste(frame, (0, 0), frame)
    return background


def extract(source: Path, output: Path, preview: Path, ranges: dict | None = None, stride: int = 1):
    capture = cv2.VideoCapture(str(source))
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not capture.isOpened() or source_fps <= 0:
        raise ValueError(f"Cannot read video: {source}")
    decoded = []
    while True:
        success, frame = capture.read()
        if not success:
            break
        decoded.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    capture.release()
    output.mkdir(parents=True, exist_ok=True)
    preview.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "actions": []}
    provenance = {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_fps": source_fps,
        "source_frames": total,
        "processing": "Crop each sticker, remove edge-connected neutral background, align to a fixed transparent canvas; preserve the recorded motion.",
        "actions": [],
    }
    samples = Image.new("RGB", (CANVAS[0] * 6, (CANVAS[1] + 24) * 2), "#f4f1e8")
    for row, (action, region) in enumerate(REGIONS.items()):
        start, end = (ranges or {}).get(action, (0, len(decoded)))
        indexes = list(range(start, end, stride))
        x1, y1, x2, y2 = region["crop"]
        raw = [remove_connected_background(decoded[i][y1:y2, x1:x2]) for i in indexes]
        bounds = [image.getbbox() for image in raw]
        common = (min(b[0] for b in bounds), min(b[1] for b in bounds),
                  max(b[2] for b in bounds), max(b[3] for b in bounds))
        width, height = common[2] - common[0], common[3] - common[1]
        scale = min(172 / width, 182 / height)
        fitted = (round(width * scale), round(height * scale))
        frames = []
        for image in raw:
            sprite = image.crop(common).resize(fitted, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", CANVAS)
            canvas.alpha_composite(sprite, ((CANVAS[0] - fitted[0]) // 2, CANVAS[1] - 8 - fitted[1]))
            frames.append(canvas)
        strip = Image.new("RGBA", (CANVAS[0] * len(frames), CANVAS[1]))
        for index, frame in enumerate(frames):
            strip.paste(frame, (index * CANVAS[0], 0))
        strip.save(output / f"{action}.png", optimize=True)
        fps = source_fps / stride
        manifest["actions"].append({
            "id": action, "name": region["name"], "sheet": f"{action}.png",
            "frame_width": CANVAS[0], "frame_height": CANVAS[1],
            "frame_count": len(frames), "fps": fps, "loops": 2, "random": True,
        })
        provenance["actions"].append({"id": action, "crop": region["crop"], "source_start_frame": start,
                                       "source_end_frame_exclusive": end, "sampling_stride": stride})
        for col in range(6):
            index = round(col * (len(frames) - 1) / 5)
            samples.paste(checker_preview(frames[index]), (col * CANVAS[0], row * (CANVAS[1] + 24)))
            ImageDraw.Draw(samples).text((col * CANVAS[0] + 8, row * (CANVAS[1] + 24) + CANVAS[1] + 4),
                                         f"{action}: {index}", fill="#474138")
        # A preview only; the application reads the lossless PNG strip.
        previews = [checker_preview(frame) for frame in frames]
        previews[0].save(preview / f"{action}.gif", save_all=True, append_images=previews[1:],
                         duration=round(1000 / fps), loop=0)
        frames[len(frames) // 2].save(preview / f"{action}.png")
        print(action, "frames", len(frames), "fps", fps, "bounds", common, "fitted", fitted)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "SOURCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    samples.save(preview / "contact.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "actions")
    parser.add_argument("--preview", type=Path, default=ROOT / "artifacts" / "action-preview")
    parser.add_argument("--ranges", type=Path, help="Optional action id to [start, end] frame mapping")
    parser.add_argument("--stride", type=int, default=1, choices=(1, 2, 3), help="Keep every Nth source frame")
    arguments = parser.parse_args()
    ranges = json.loads(arguments.ranges.read_text(encoding="utf-8")) if arguments.ranges else None
    extract(arguments.source, arguments.output, arguments.preview, ranges, arguments.stride)
