"""Shared icon tinting helper for action state display."""

from __future__ import annotations

import hashlib
from pathlib import Path

# Active state: mint green (matches lan-mouse active icon color)
COLOR_ACTIVE: tuple[int, int, int, int] = (159, 210, 167, 255)
# Inactive state: white
COLOR_INACTIVE: tuple[int, int, int, int] = (255, 255, 255, 255)

# Background colors
BG_ACTIVE: list[int] = [39, 42, 39, 255]
BG_INACTIVE: list[int] = [40, 36, 27, 255]

_CACHE_DIR: Path = Path(__file__).parent / ".icon_cache"


def tint_icon(base_path: str, color: tuple[int, int, int, int]) -> str | None:
    """Return path to a cached tinted PNG of base_path.

    Uses a deterministic filename based on the source path and color,
    so tinted icons are reused across restarts. Returns None if Pillow
    is unavailable.
    """
    key = f"{base_path}:{color[0]},{color[1]},{color[2]},{color[3]}"
    cache_name = hashlib.md5(key.encode()).hexdigest() + ".png"
    cache_path = _CACHE_DIR / cache_name

    if cache_path.is_file():
        return str(cache_path)

    try:
        from PIL import Image
    except ImportError:
        return None

    _CACHE_DIR.mkdir(exist_ok=True)
    img = Image.open(base_path).convert("RGBA")
    tinted = Image.new("RGBA", img.size, (color[0], color[1], color[2], 255))
    _, _, _, alpha = img.split()
    tinted.putalpha(alpha)
    tinted.save(cache_path)
    return str(cache_path)
