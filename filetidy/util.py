"""Small helpers shared across filetidy: parsing, formatting, safe paths."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

_SIZE_UNITS = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024 ** 2,
    "mb": 1024 ** 2,
    "g": 1024 ** 3,
    "gb": 1024 ** 3,
    "t": 1024 ** 4,
    "tb": 1024 ** 4,
}

_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 7 * 86400,
    "y": 365 * 86400,
}

# Characters no mainstream filesystem is happy about, plus the path separators.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class ParseError(ValueError):
    """Raised when user-supplied text cannot be interpreted."""


def parse_size(text: str | int | float) -> int:
    """Parse '10MB', '1.5g', '512', 4096 into a byte count."""
    if isinstance(text, (int, float)):
        return int(text)
    raw = str(text).strip().lower().replace(" ", "").replace(",", "")
    if not raw:
        raise ParseError("empty size")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]*)", raw)
    if not match:
        raise ParseError(f"cannot parse size: {text!r}")
    number, unit = match.groups()
    if unit and unit not in _SIZE_UNITS:
        raise ParseError(f"unknown size unit: {unit!r} (use b/kb/mb/gb/tb)")
    return int(float(number) * _SIZE_UNITS.get(unit or "b", 1))


def human_size(num_bytes: int) -> str:
    """Render a byte count the way a human would read it."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def parse_age(text: str, now: datetime | None = None) -> datetime:
    """Parse '7d', '12h', '2w' or an ISO date into an absolute cutoff timestamp."""
    now = now or datetime.now()
    raw = str(text).strip().lower()
    if not raw:
        raise ParseError("empty age")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhdwy])", raw)
    if match:
        number, unit = match.groups()
        return now - timedelta(seconds=float(number) * _DURATION_UNITS[unit])
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ParseError(
            f"cannot parse age: {text!r} (use 7d, 12h, 2w or 2026-01-01)"
        ) from exc


def split_name(path: Path) -> tuple[str, str]:
    """Split into (stem, extension-without-dot), handling dotfiles and .tar.gz."""
    name = path.name
    if name.startswith(".") and name.count(".") == 1:
        return name, ""  # .gitignore -> no extension
    for double in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if name.lower().endswith(double):
            return name[: -len(double)], double[1:]
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name, ""
    return stem, ext


def sanitize_component(text: str, replacement: str = "_") -> str:
    """Make a single path component safe on every platform we care about."""
    cleaned = _ILLEGAL_CHARS.sub(replacement, text).strip().rstrip(".")
    if not cleaned:
        return replacement
    if cleaned.split(".")[0].lower() in _WINDOWS_RESERVED:
        cleaned = f"{replacement}{cleaned}"
    return cleaned[:200]


def slugify(text: str) -> str:
    """ASCII, lowercase, dash-separated - handy for --slug renames."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "file"


def unique_path(dest: Path, taken: set[Path] | None = None) -> Path:
    """Return `dest`, or dest with a ' (1)', ' (2)'... suffix if it is occupied."""
    taken = taken if taken is not None else set()
    if not dest.exists() and dest not in taken:
        return dest
    stem, ext = split_name(dest)
    suffix = f".{ext}" if ext else ""
    for counter in range(1, 10_000):
        candidate = dest.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists() and candidate not in taken:
            return candidate
    raise ParseError(f"cannot find a free name near {dest}")


def is_within(path: Path, parent: Path) -> bool:
    """True when `path` lives inside `parent` (no symlink resolution surprises)."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
