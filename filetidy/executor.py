"""Applying a plan, journalling what happened, and undoing it later.

Two guarantees the rest of the tool leans on:
  * every executed run writes a journal, so `tidy undo` can walk it backwards;
  * deletes move files into a local trash folder unless --hard-delete is given.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .plan import DELETE, MOVE, RENAME, Action, Plan
from .util import unique_path

DEFAULT_HOME = Path.home() / ".filetidy"
TEMP_PREFIX = ".filetidy-tmp-"


@dataclass
class RunResult:
    run_id: str
    journal: Path | None
    applied: list[Action] = field(default_factory=list)
    failed: list[tuple[Action, str]] = field(default_factory=list)
    trash_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.failed


class Journal:
    """Append-only record of one run, written as JSON Lines."""

    def __init__(self, path: Path, run_id: str, command: str, root: Path | None):
        self.path = path
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write(
            {
                "type": "header",
                "run_id": run_id,
                "command": command,
                "root": str(root) if root else None,
                "started": datetime.now().isoformat(timespec="seconds"),
            }
        )

    def _write(self, entry: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def record_move(self, source: Path, dest: Path, kind: str = MOVE) -> None:
        self._write({"type": kind, "source": str(source), "dest": str(dest)})

    def record_trash(self, source: Path, trashed: Path) -> None:
        self._write({"type": "trash", "source": str(source), "dest": str(trashed)})

    def record_hard_delete(self, source: Path) -> None:
        self._write({"type": "hard_delete", "source": str(source)})

    def record_mkdir(self, path: Path) -> None:
        self._write({"type": "mkdir", "path": str(path)})

    def close(self, applied: int, failed: int) -> None:
        self._write({"type": "footer", "applied": applied, "failed": failed})


def journal_dir(base: Path | None = None) -> Path:
    return (base or DEFAULT_HOME) / "history"


def trash_dir(run_id: str, base: Path | None = None) -> Path:
    return (base or DEFAULT_HOME) / "trash" / run_id


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _ensure_parent(path: Path, journal: Journal | None) -> None:
    parent = path.parent
    if parent.exists():
        return
    missing = []
    probe = parent
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    parent.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        if journal:
            journal.record_mkdir(created)


def _move(source: Path, dest: Path) -> None:
    """Move across filesystems if needed; never silently clobber a directory."""
    if dest.is_dir() and not dest.is_symlink():
        raise IsADirectoryError(f"destination is a directory: {dest}")
    shutil.move(str(source), str(dest))


def execute(
    plan: Plan,
    *,
    command: str = "tidy",
    base: Path | None = None,
    hard_delete: bool = False,
    write_journal: bool = True,
    now: datetime | None = None,
) -> RunResult:
    """Apply every action in `plan`, recording enough to undo it."""
    run_id = new_run_id(now)
    journal: Journal | None = None
    if write_journal and plan.actions:
        journal = Journal(
            journal_dir(base) / f"{run_id}.jsonl", run_id, command, plan.root
        )
    result = RunResult(run_id=run_id, journal=journal.path if journal else None)
    trash = trash_dir(run_id, base)

    sources = {action.source for action in plan.actions}
    deferred: list[tuple[Action, Path]] = []

    for index, action in enumerate(plan.actions):
        try:
            if action.kind == DELETE:
                _apply_delete(action, trash, journal, hard_delete, result)
                continue
            assert action.dest is not None
            if action.dest in sources:
                # The destination is occupied by a file that is itself moving:
                # park this one under a temp name and finish in the second pass.
                temp = action.source.with_name(
                    f"{TEMP_PREFIX}{index}-{action.source.name}"
                )
                _move(action.source, temp)
                deferred.append((action, temp))
                continue
            _apply_move(action, action.source, trash, journal, result)
        except OSError as exc:
            result.failed.append((action, str(exc)))

    for action, temp in deferred:
        try:
            _apply_move(action, temp, trash, journal, result)
        except OSError as exc:
            # Put it back where it came from rather than leaving a temp file behind.
            try:
                _move(temp, action.source)
            except OSError:
                pass
            result.failed.append((action, str(exc)))

    if trash.exists():
        result.trash_dir = trash
    if journal:
        journal.close(len(result.applied), len(result.failed))
    return result


def _apply_move(
    action: Action,
    source: Path,
    trash: Path,
    journal: Journal | None,
    result: RunResult,
) -> None:
    assert action.dest is not None
    _ensure_parent(action.dest, journal)
    if action.dest.exists():
        # Overwrite policy: keep the displaced file in trash so undo stays honest.
        displaced = trash / action.dest.name
        displaced.parent.mkdir(parents=True, exist_ok=True)
        displaced = unique_path(displaced)
        _move(action.dest, displaced)
        if journal:
            journal.record_trash(action.dest, displaced)
    _move(source, action.dest)
    if journal:
        journal.record_move(action.source, action.dest, action.kind)
    result.applied.append(action)


def _apply_delete(
    action: Action,
    trash: Path,
    journal: Journal | None,
    hard_delete: bool,
    result: RunResult,
) -> None:
    if hard_delete:
        os.remove(action.source)
        if journal:
            journal.record_hard_delete(action.source)
        result.applied.append(action)
        return
    trash.mkdir(parents=True, exist_ok=True)
    target = unique_path(trash / action.source.name)
    _move(action.source, target)
    if journal:
        journal.record_trash(action.source, target)
    result.applied.append(action)


# --------------------------------------------------------------------------- undo


def list_journals(base: Path | None = None, include_undone: bool = False) -> list[Path]:
    """Journals oldest-first. Undone runs are hidden unless asked for."""
    directory = journal_dir(base)
    if not directory.is_dir():
        return []
    journals = list(directory.glob("*.jsonl"))
    if include_undone:
        journals += list(directory.glob("*.jsonl.undone"))
    return sorted(journals, key=lambda path: path.name)


def read_journal(path: Path) -> list[dict]:
    entries = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def describe_journal(path: Path) -> str:
    entries = read_journal(path)
    header = next((e for e in entries if e.get("type") == "header"), {})
    footer = next((e for e in entries if e.get("type") == "footer"), {})
    moves = sum(1 for e in entries if e.get("type") in (MOVE, RENAME))
    trashed = sum(1 for e in entries if e.get("type") == "trash")
    deleted = sum(1 for e in entries if e.get("type") == "hard_delete")
    name = path.name.split(".jsonl")[0]
    state = "  [undone]" if path.name.endswith(".undone") else ""
    return (
        f"{name}  {header.get('started', '?')}  {header.get('command', '?')}{state}\n"
        f"    {moves} move/rename, {trashed} trashed, {deleted} hard-deleted, "
        f"{footer.get('failed', 0)} failed"
    )


@dataclass
class UndoResult:
    restored: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)
    removed_dirs: int = 0


def undo(journal_path: Path, dry_run: bool = False) -> UndoResult:
    """Walk a journal backwards, putting every file back where it started."""
    entries = read_journal(journal_path)
    result = UndoResult()
    created_dirs: list[Path] = []

    for entry in reversed(entries):
        kind = entry.get("type")
        if kind == "mkdir":
            created_dirs.append(Path(entry["path"]))
            continue
        if kind == "hard_delete":
            result.unrecoverable.append(entry["source"])
            continue
        if kind not in (MOVE, RENAME, "trash"):
            continue
        source = Path(entry["source"])
        dest = Path(entry["dest"])
        if not dest.exists():
            result.failed.append((str(dest), "no longer present"))
            continue
        if source.exists():
            result.failed.append((str(source), "original path is occupied again"))
            continue
        if dry_run:
            result.restored += 1
            continue
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            _move(dest, source)
            result.restored += 1
        except OSError as exc:
            result.failed.append((str(dest), str(exc)))

    for directory in created_dirs:
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                if not dry_run:
                    directory.rmdir()
                result.removed_dirs += 1
        except OSError:
            pass
    return result
