"""Inline SVG icons — rendered once into a temp asset dir.

Used from QSS (``image: url(...)`` via :func:`url`) and from code as
``QIcon`` (via :func:`icon`). No asset pipeline, no qrc file.
"""
import tempfile
from pathlib import Path

from PySide6.QtGui import QIcon

_ASSET_DIR: Path | None = None

# icon name -> inner SVG body; {c} is substituted with the stroke/fill color.
_BODIES: dict[str, str] = {
    "home": (
        '<path stroke="{c}" d="M4 11 12 4l8 7"/>'
        '<path stroke="{c}" d="M6 10v10h12V10"/>'
        '<path stroke="{c}" d="M10 20v-5h4v5"/>'
    ),
    "shorts": (
        '<rect stroke="{c}" x="3" y="5" width="18" height="14" rx="3"/>'
        '<path fill="{c}" d="M10.2 9.2v5.6l4.6-2.8z"/>'
    ),
    "tiktok": (
        '<path stroke="{c}" d="M9 18V6l8-2v12"/>'
        '<circle fill="{c}" stroke="none" cx="6.8" cy="18" r="1.7"/>'
        '<circle fill="{c}" stroke="none" cx="14.8" cy="16" r="1.7"/>'
    ),
    "swap": (
        '<path stroke="{c}" d="M4 8h13"/>'
        '<path stroke="{c}" d="m14 5 3 3-3 3"/>'
        '<path stroke="{c}" d="M20 16H7"/>'
        '<path stroke="{c}" d="m10 13-3 3 3 3"/>'
    ),
    "sliders": (
        '<path stroke="{c}" d="M3 7h13"/>'
        '<path stroke="{c}" d="M19 7h2"/>'
        '<path stroke="{c}" d="M3 12h5"/>'
        '<path stroke="{c}" d="M11 12h10"/>'
        '<path stroke="{c}" d="M3 17h9"/>'
        '<path stroke="{c}" d="M15 17h6"/>'
        '<circle fill="{c}" stroke="none" cx="17" cy="7" r="2"/>'
        '<circle fill="{c}" stroke="none" cx="9" cy="12" r="2"/>'
        '<circle fill="{c}" stroke="none" cx="13" cy="17" r="2"/>'
    ),
    "terminal": (
        '<rect stroke="{c}" x="3" y="5" width="18" height="14" rx="2"/>'
        '<path stroke="{c}" d="m7 9 4 3-4 3"/>'
        '<path stroke="{c}" d="M13 15h4"/>'
    ),
    "play": '<path fill="{c}" d="M8 5.5v13l10.5-6.5z"/>',
    "pause": '<path fill="{c}" d="M8 5h3v14H8zM13 5h3v14h-3z"/>',
    "stop": '<rect fill="{c}" x="7" y="7" width="10" height="10" rx="2"/>',
    "plus": '<path stroke="{c}" d="M12 5v14M5 12h14"/>',
    "trash": (
        '<path stroke="{c}" d="M5 7h14"/>'
        '<path stroke="{c}" d="M9 7V5h6v2"/>'
        '<path stroke="{c}" d="m7 7 1 13h8l1-13"/>'
    ),
    "folder": (
        '<path stroke="{c}" d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
    ),
    "image": (
        '<rect stroke="{c}" x="3" y="5" width="18" height="14" rx="2"/>'
        '<circle stroke="{c}" cx="8.5" cy="10" r="1.4"/>'
        '<path stroke="{c}" d="m5 19 5-5 3 3 4-4 4 4"/>'
    ),
    "film": (
        '<rect stroke="{c}" x="3" y="5" width="18" height="14" rx="2"/>'
        '<path stroke="{c}" d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"/>'
    ),
    "chevron-down": '<path stroke="{c}" d="m6 9 6 6 6-6"/>',
    "check": '<path stroke="{c}" d="m5 13 4 4 10-11"/>',
    "search": '<circle stroke="{c}" cx="10.5" cy="10.5" r="6"/><path stroke="{c}" d="m15 15 5.5 5.5"/>',
    "warning": (
        '<path stroke="{c}" d="M12 4 3.5 19.5h17z"/>'
        '<path stroke="{c}" d="M12 10v4"/>'
        '<circle fill="{c}" stroke="none" cx="12" cy="17.6" r="1"/>'
    ),
    "spark": (
        '<path stroke="{c}" d="m12 3 1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z"/>'
    ),
    "volume": (
        '<path stroke="{c}" d="M4 9v6h4l5 4V5L8 9z"/>'
        '<path stroke="{c}" d="M16.5 8.5a5 5 0 0 1 0 7"/>'
        '<path stroke="{c}" d="M19 6a9 9 0 0 1 0 12"/>'
    ),
    "mute": (
        '<path stroke="{c}" d="M4 9v6h4l5 4V5L8 9z"/>'
        '<path stroke="{c}" d="m16 9.5 5 5M21 9.5l-5 5"/>'
    ),
    "fullscreen": (
        '<path stroke="{c}" d="M4 9V4h5"/>'
        '<path stroke="{c}" d="M20 9V4h-5"/>'
        '<path stroke="{c}" d="M4 15v5h5"/>'
        '<path stroke="{c}" d="M20 15v5h-5"/>'
    ),
    "copy": (
        '<rect stroke="{c}" x="9" y="9" width="12" height="12" rx="2"/>'
        '<path stroke="{c}" d="M5 15V5a2 2 0 0 1 2-2h10"/>'
    ),
    "download": (
        '<path stroke="{c}" d="M12 4v10"/>'
        '<path stroke="{c}" d="m8 10 4 4 4-4"/>'
        '<path stroke="{c}" d="M5 19h14"/>'
    ),
    "clock": (
        '<circle stroke="{c}" cx="12" cy="12" r="9"/>'
        '<path stroke="{c}" d="M12 7v5l3 3"/>'
    ),
}

_NEUTRAL = "#98a0b5"


def asset_dir() -> Path:
    global _ASSET_DIR
    if _ASSET_DIR is None:
        _ASSET_DIR = Path(tempfile.gettempdir()) / "clipclipper_ui_assets"
        _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    return _ASSET_DIR


def asset(name: str, color: str = _NEUTRAL, size: int = 24) -> Path:
    """Render (once) and return the SVG file path for an icon."""
    body = _BODIES.get(name)
    if body is None:
        raise KeyError(f"unknown icon: {name}")
    path = asset_dir() / f"{name}_{color.strip('#')}_{size}.svg"
    if not path.is_file():
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'{body.replace("{c}", color)}'
            f"</svg>"
        )
        path.write_text(svg, encoding="utf-8")
    return path


def url(name: str, color: str = _NEUTRAL, size: int = 24) -> str:
    """Filesystem URL usable inside QSS ``image: url(...)``."""
    return asset(name, color, size).as_posix().replace(" ", "%20")


def icon(name: str, color: str = _NEUTRAL, size: int = 24) -> QIcon:
    return QIcon(str(asset(name, color, size)))
