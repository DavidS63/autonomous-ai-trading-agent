"""Walking a folder and deciding which files are in scope."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .util import split_name

# Never touch our own bookkeeping, VCS metadata, or OS junk.
SKIP_DIRS = {".git", ".hg", ".svn", ".filetidy", "__pycache__", ".venv", "node_modules"}
SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


@dataclass
class FileInfo:
    """A scanned file plus the stat data every stage needs."""

    path: Path
    root: Path
    size: int
    modified: datetime
    created: datetime

    @property
    def stem(self) -> str:
        return split_name(self.path)[0]

    @property
    def ext(self) -> str:
        return split_name(self.path)[1]

    @property
    def relative(self) -> Path:
        return self.path.relative_to(self.root)


@dataclass
class ScanOptions:
    """Everything the CLI's shared filtering flags map onto."""

    recursive: bool = False
    max_depth: int | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    include_hidden: bool = False
    min_size: int | None = None
    max_size: int | None = None
    newer_than: datetime | None = None
    older_than: datetime | None = None
    follow_symlinks: bool = False
    skip_dirs: set[str] = field(default_factory=lambda: set(SKIP_DIRS))

    def matches(self, info: FileInfo) -> bool:
        name = info.path.name
        rel = info.relative.as_posix()
        if not self.include_hidden and any(
            part.startswith(".") for part in info.relative.parts
        ):
            return False
        if name in SKIP_NAMES:
            return False
        if self.extensions:
            wanted = {e.lower().lstrip(".") for e in self.extensions}
            if info.ext.lower() not in wanted:
                return False
        if self.include and not any(
            fnmatch.fnmatch(name.lower(), pattern.lower())
            or fnmatch.fnmatch(rel.lower(), pattern.lower())
            for pattern in self.include
        ):
            return False
        if any(
            fnmatch.fnmatch(name.lower(), pattern.lower())
            or fnmatch.fnmatch(rel.lower(), pattern.lower())
            for pattern in self.exclude
        ):
            return False
        if self.min_size is not None and info.size < self.min_size:
            return False
        if self.max_size is not None and info.size > self.max_size:
            return False
        if self.newer_than is not None and info.modified < self.newer_than:
            return False
        if self.older_than is not None and info.modified > self.older_than:
            return False
        return True


def _file_info(path: Path, root: Path) -> FileInfo | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    # st_birthtime exists on macOS/BSD; st_ctime is the closest stand-in elsewhere.
    created_ts = getattr(stat, "st_birthtime", None) or stat.st_ctime
    return FileInfo(
        path=path,
        root=root,
        size=stat.st_size,
        modified=datetime.fromtimestamp(stat.st_mtime),
        created=datetime.fromtimestamp(created_ts),
    )


def scan(root: Path, options: ScanOptions) -> list[FileInfo]:
    """Collect the in-scope files under `root`, sorted for stable output."""
    return sorted(iter_scan(root, options), key=lambda info: str(info.path).lower())


def iter_scan(root: Path, options: ScanOptions) -> Iterator[FileInfo]:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=options.follow_symlinks):
        current = Path(dirpath)
        depth = len(current.relative_to(root).parts)
        prune = not options.recursive or (
            options.max_depth is not None and depth >= options.max_depth
        )
        dirnames[:] = [] if prune else [
            d for d in sorted(dirnames)
            if d not in options.skip_dirs
            and (options.include_hidden or not d.startswith("."))
        ]
        for filename in sorted(filenames):
            path = current / filename
            if path.is_symlink() and not options.follow_symlinks:
                continue
            info = _file_info(path, root)
            if info and options.matches(info):
                yield info
