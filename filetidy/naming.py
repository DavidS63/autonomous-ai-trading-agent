"""Pattern -> filename rendering for `tidy rename` and rule targets.

Supported tokens (all optional, all usable in rule targets too):

    {name}      original stem, extension stripped
    {ext}       extension without the dot ('pdf')
    {parent}    name of the containing folder
    {project}   value of --project, defaults to the folder name
    {category}  Documents / Images / ... (see categories.py)
    {n}         running counter, format it with {n:03} for 001
    {size}      size in bytes; {size} is raw, use {sizeh} for '1.4 MB'
    {hash}      first 8 chars of the content hash
    {date}      modified date, default %Y-%m-%d, override with {date:%Y-%m}
    {modified}  same as {date}
    {created}   creation date, same formatting rules
    {now}       time of the run, same formatting rules
"""

from __future__ import annotations

import string
from datetime import datetime
from pathlib import Path

from .categories import category_for
from .filters import FileInfo
from .hashing import file_hash
from .util import ParseError, human_size, sanitize_component, slugify

DEFAULT_DATE_FORMAT = "%Y-%m-%d"

KNOWN_TOKENS = (
    "name", "ext", "parent", "project", "category", "n", "size", "sizeh",
    "hash", "date", "modified", "created", "now",
)


class DateToken:
    """A datetime that formats as %Y-%m-%d unless the pattern says otherwise."""

    def __init__(self, value: datetime, default: str = DEFAULT_DATE_FORMAT):
        self.value = value
        self.default = default

    def __format__(self, spec: str) -> str:
        return self.value.strftime(spec or self.default)

    def __str__(self) -> str:
        return format(self, "")


class _StrictFormatter(string.Formatter):
    """str.format with a friendlier error for typo'd tokens."""

    def get_value(self, key, args, kwargs):  # type: ignore[override]
        if isinstance(key, str) and key not in kwargs:
            raise ParseError(
                f"unknown token {{{key}}} - available: {', '.join(KNOWN_TOKENS)}"
            )
        return super().get_value(key, args, kwargs)


_FORMATTER = _StrictFormatter()


def build_tokens(
    info: FileInfo,
    counter: int = 1,
    project: str | None = None,
    now: datetime | None = None,
    want_hash: bool = False,
) -> dict[str, object]:
    """Assemble the token table for one file. Hashing is opt-in (it reads bytes)."""
    return {
        "name": info.stem,
        "ext": info.ext,
        "parent": info.path.parent.name,
        "project": project or info.root.name,
        "category": category_for(info.ext),
        "n": counter,
        "size": info.size,
        "sizeh": human_size(info.size),
        "hash": file_hash(info.path)[:8] if want_hash else "",
        "date": DateToken(info.modified),
        "modified": DateToken(info.modified),
        "created": DateToken(info.created),
        "now": DateToken(now or datetime.now()),
    }


def pattern_uses(pattern: str, token: str) -> bool:
    """True when `pattern` references {token} (with or without a format spec)."""
    for _, field_name, _, _ in string.Formatter().parse(pattern):
        if field_name is not None and field_name.split(".")[0].split("[")[0] == token:
            return True
    return False


def render(pattern: str, tokens: dict[str, object]) -> str:
    """Render a pattern; raises ParseError on unknown tokens or bad format specs."""
    try:
        return _FORMATTER.vformat(pattern, (), tokens)
    except ParseError:
        raise
    except (KeyError, IndexError) as exc:
        raise ParseError(f"unknown token in pattern {pattern!r}: {exc}") from exc
    except ValueError as exc:
        raise ParseError(f"bad pattern {pattern!r}: {exc}") from exc


def render_filename(
    pattern: str,
    info: FileInfo,
    counter: int = 1,
    project: str | None = None,
    now: datetime | None = None,
    auto_ext: bool = True,
    slug: bool = False,
    lower: bool = False,
) -> str:
    """Render a pattern into a single, filesystem-safe filename."""
    tokens = build_tokens(
        info, counter=counter, project=project, now=now,
        want_hash=pattern_uses(pattern, "hash"),
    )
    rendered = render(pattern, tokens).strip()
    if not rendered:
        raise ParseError(f"pattern {pattern!r} produced an empty name")
    if auto_ext and info.ext and not rendered.lower().endswith(f".{info.ext.lower()}"):
        rendered = f"{rendered}.{info.ext}"
    if slug:
        stem, dot, ext = rendered.rpartition(".")
        rendered = f"{slugify(stem)}.{ext.lower()}" if dot else slugify(rendered)
    if lower:
        rendered = rendered.lower()
    return sanitize_component(rendered)


def render_subpath(pattern: str, tokens: dict[str, object]) -> Path:
    """Render a rule target like 'Finance/{date:%Y}' into a relative Path."""
    rendered = render(pattern, tokens).strip().strip("/\\")
    if not rendered:
        raise ParseError(f"target pattern {pattern!r} produced an empty path")
    parts = [
        sanitize_component(part)
        for part in rendered.replace("\\", "/").split("/")
        if part not in ("", ".")
    ]
    if not parts:
        raise ParseError(f"target pattern {pattern!r} produced an empty path")
    return Path(*parts)
