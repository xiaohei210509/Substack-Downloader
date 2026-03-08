#!/usr/bin/env python3

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / ".icon_build"
ICONSET_DIR = BUILD_DIR / "AppIcon.iconset"
MASTER_PATH = BUILD_DIR / "AppIcon-1024.png"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))


def rounded_rectangle_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def create_background(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    top = (13, 33, 61)
    bottom = (38, 108, 140)
    glow = (120, 213, 208)
    center_x = size * 0.68
    center_y = size * 0.24
    max_distance = math.sqrt(size * size + size * size)

    for y in range(size):
        vertical_t = y / max(1, size - 1)
        base = mix_color(top, bottom, vertical_t)
        for x in range(size):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx * dx + dy * dy) / max_distance
            glow_strength = max(0.0, 1.0 - distance * 3.2)
            color = mix_color(base, glow, glow_strength * 0.75)
            pixels[x, y] = (*color, 255)

    mask = rounded_rectangle_mask(size, int(size * 0.23))
    image.putalpha(mask)
    return image


def draw_document(draw: ImageDraw.ImageDraw, size: int) -> None:
    left = size * 0.23
    top = size * 0.18
    right = size * 0.67
    bottom = size * 0.79
    corner = size * 0.06

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (left + size * 0.018, top + size * 0.022, right + size * 0.018, bottom + size * 0.022),
        radius=corner,
        fill=(2, 18, 34, 70),
    )
    shadow_blur = shadow.filter(ImageFilter.GaussianBlur(radius=size * 0.015))
    draw._image.alpha_composite(shadow_blur)

    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=corner,
        fill=(245, 250, 252, 255),
    )

    fold = [
        (right - size * 0.12, top),
        (right, top),
        (right, top + size * 0.12),
    ]
    draw.polygon(fold, fill=(214, 227, 234, 255))

    line_color = (75, 94, 116, 255)
    line_width = max(3, int(size * 0.012))
    for index, width_ratio in enumerate((0.64, 0.58, 0.68, 0.52)):
        y = top + size * (0.13 + index * 0.095)
        x2 = left + size * width_ratio
        draw.rounded_rectangle(
            (left + size * 0.06, y, x2, y + line_width),
            radius=line_width // 2,
            fill=line_color,
        )


def draw_translation_badge(draw: ImageDraw.ImageDraw, size: int) -> None:
    cx = size * 0.68
    cy = size * 0.69
    radius = size * 0.16

    badge_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    badge_shadow_draw = ImageDraw.Draw(badge_shadow)
    badge_shadow_draw.ellipse(
        (cx - radius + size * 0.012, cy - radius + size * 0.016, cx + radius + size * 0.012, cy + radius + size * 0.016),
        fill=(3, 18, 31, 80),
    )
    draw._image.alpha_composite(badge_shadow.filter(ImageFilter.GaussianBlur(radius=size * 0.015)))

    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(22, 196, 167, 255),
    )
    draw.ellipse(
        (cx - radius * 0.77, cy - radius * 0.77, cx + radius * 0.77, cy + radius * 0.77),
        fill=(9, 61, 84, 255),
    )

    arrow_color = (237, 252, 252, 255)
    stroke = max(6, int(size * 0.016))

    draw.arc(
        (cx - radius * 0.92, cy - radius * 0.92, cx + radius * 0.92, cy + radius * 0.92),
        start=210,
        end=20,
        fill=arrow_color,
        width=stroke,
    )
    draw.arc(
        (cx - radius * 0.92, cy - radius * 0.92, cx + radius * 0.92, cy + radius * 0.92),
        start=40,
        end=200,
        fill=arrow_color,
        width=stroke,
    )

    draw.polygon(
        [
            (cx + radius * 0.75, cy - radius * 0.23),
            (cx + radius * 0.5, cy - radius * 0.35),
            (cx + radius * 0.53, cy - radius * 0.07),
        ],
        fill=arrow_color,
    )
    draw.polygon(
        [
            (cx - radius * 0.72, cy + radius * 0.26),
            (cx - radius * 0.46, cy + radius * 0.37),
            (cx - radius * 0.5, cy + radius * 0.1),
        ],
        fill=arrow_color,
    )


def create_master_icon(size: int = 1024) -> Image.Image:
    background = create_background(size)
    draw = ImageDraw.Draw(background)
    draw_document(draw, size)
    draw_translation_badge(draw, size)
    return background


def export_iconset(master: Image.Image) -> None:
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    specs = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for filename, size in specs.items():
        resized = master.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(ICONSET_DIR / filename)


def main() -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    master = create_master_icon(1024)
    master.save(MASTER_PATH)
    export_iconset(master)
    print(f"Generated iconset at: {ICONSET_DIR}")


if __name__ == "__main__":
    main()
