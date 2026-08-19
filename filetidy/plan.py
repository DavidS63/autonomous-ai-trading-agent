"""The plan: an ordered list of moves/renames/deletes, and how it is built.

Nothing here touches the filesystem beyond reading stats and hashes - building a
plan is always safe, which is what makes `--dry-run` the default everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .categories import category_for
from .filters import FileInfo
from .naming import DateToken, build_tokens, render_filename, render_subpath
from .rules import RuleSet
from .util import ParseError, human_size, split_name, unique_path

MOVE = "move"
RENAME = "rename"
DELETE = "delete"

CONFLICT_NUMBER = "number"
CONFLICT_SKIP = "skip"
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_POLICIES = (CONFLICT_NUMBER, CONFLICT_SKIP, CONFLICT_OVERWRITE)


def _display(path: Path | None, base: Path | None) -> str:
    """Show paths relative to the folder being worked on - absolute paths are noise."""
    if path is None:
        return "-"
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return str(path)


@dataclass
class Action:
    kind: str
    source: Path
    dest: Path | None
    reason: str = ""
    size: int = 0

    def describe(self, base: Path | None = None) -> str:
        source = _display(self.source, base)
        if self.kind == DELETE:
            return f"delete  {source}  ({human_size(self.size)}; {self.reason})"
        if self.kind == RENAME and self.dest is not None:
            return f"rename  {source}\n          -> {self.dest.name}"
        return f"move    {source}\n          -> {_display(self.dest, base)}"


@dataclass
class Skipped:
    path: Path
    reason: str


@dataclass
class Plan:
    """Actions plus the files we deliberately left alone."""

    actions: list[Action] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    root: Path | None = None

    def __len__(self) -> int:
        return len(self.actions)

    @property
    def bytes_touched(self) -> int:
        return sum(action.size for action in self.actions)

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for action in self.actions:
            tally[action.kind] = tally.get(action.kind, 0) + 1
        return tally


class DestinationAllocator:
    """Hands out destination paths, applying the conflict policy exactly once."""

    def __init__(self, policy: str = CONFLICT_NUMBER, sources: set[Path] | None = None):
        if policy not in CONFLICT_POLICIES:
            raise ParseError(f"unknown conflict policy: {policy!r}")
        self.policy = policy
        self.claimed: set[Path] = set()
        # Files we are moving away no longer occupy their old spot.
        self.sources = sources or set()

    def _occupied(self, path: Path) -> bool:
        if path in self.claimed:
            return True
        return path.exists() and path not in self.sources

    def allocate(self, dest: Path) -> Path | None:
        """Return a usable destination, or None when the policy says to skip."""
        if not self._occupied(dest):
            self.claimed.add(dest)
            return dest
        if self.policy == CONFLICT_SKIP:
            return None
        if self.policy == CONFLICT_OVERWRITE and dest not in self.claimed:
            self.claimed.add(dest)
            return dest
        candidate = unique_path(dest, self.claimed)
        self.claimed.add(candidate)
        return candidate

    def release(self, path: Path) -> None:
        self.claimed.discard(path)


def _date_folder(info: FileInfo, date_format: str, source: str) -> Path:
    stamp = info.created if source == "created" else info.modified
    return render_subpath(f"{{value:{date_format}}}", {"value": DateToken(stamp)})


def _sort_subpath(
    info: FileInfo,
    components: list[str],
    date_format: str,
    date_source: str,
) -> Path:
    parts: list[Path] = []
    for component in components:
        if component == "type":
            parts.append(Path(category_for(info.ext)))
        elif component == "ext":
            parts.append(Path(info.ext.lower() or "no-extension"))
        elif component == "date":
            parts.append(_date_folder(info, date_format, date_source))
        else:
            raise ParseError(f"unknown --by component: {component!r}")
    return Path(*parts) if parts else Path()


def plan_sort(
    files: list[FileInfo],
    dest_root: Path,
    components: list[str],
    *,
    ruleset: RuleSet | None = None,
    date_format: str = "%Y-%m",
    date_source: str = "modified",
    rename_pattern: str | None = None,
    project: str | None = None,
    conflict: str = CONFLICT_NUMBER,
    now: datetime | None = None,
) -> Plan:
    """Work out where every scanned file should end up."""
    now = now or datetime.now()
    plan = Plan(root=dest_root)
    allocator = DestinationAllocator(conflict, sources={info.path for info in files})
    use_rules = "rules" in components
    folder_components = [c for c in components if c != "rules"]
    counters: dict[Path, int] = {}

    for info in files:
        rule = ruleset.match(info) if (use_rules and ruleset) else None
        tokens = build_tokens(info, project=project, now=now)
        if rule is not None:
            subpath = render_subpath(rule.target, tokens)
            reason = f"rule: {rule.name}"
            pattern = rule.rename or rename_pattern
        elif folder_components:
            subpath = _sort_subpath(info, folder_components, date_format, date_source)
            reason = "by " + "/".join(folder_components)
            pattern = rename_pattern
        elif use_rules and ruleset and ruleset.default_target:
            subpath = render_subpath(ruleset.default_target, tokens)
            reason = "default target"
            pattern = rename_pattern
        else:
            plan.skipped.append(Skipped(info.path, "no rule matched"))
            continue

        target_dir = dest_root / subpath
        if pattern:
            counters[target_dir] = counters.get(target_dir, 0) + 1
            filename = render_filename(
                pattern, info, counter=counters[target_dir], project=project, now=now
            )
        else:
            filename = info.path.name

        candidate = target_dir / filename
        if candidate == info.path:
            plan.skipped.append(Skipped(info.path, "already in place"))
            continue
        dest = allocator.allocate(candidate)
        if dest is None:
            plan.skipped.append(Skipped(info.path, f"destination exists: {candidate}"))
            continue
        plan.actions.append(
            Action(kind=MOVE, source=info.path, dest=dest, reason=reason, size=info.size)
        )
    return plan


_SORT_KEYS = {
    "name": lambda info: (info.path.name.lower(), str(info.path).lower()),
    "path": lambda info: str(info.path).lower(),
    "date": lambda info: (info.modified, str(info.path).lower()),
    "created": lambda info: (info.created, str(info.path).lower()),
    "size": lambda info: (info.size, str(info.path).lower()),
    "ext": lambda info: (info.ext.lower(), info.path.name.lower()),
}


def plan_rename(
    files: list[FileInfo],
    pattern: str,
    *,
    project: str | None = None,
    sort_by: str = "name",
    reverse: bool = False,
    start: int = 1,
    step: int = 1,
    counter_scope: str = "dir",
    conflict: str = CONFLICT_NUMBER,
    auto_ext: bool = True,
    slug: bool = False,
    lower: bool = False,
    now: datetime | None = None,
) -> Plan:
    """Rename files in place according to `pattern`."""
    if sort_by not in _SORT_KEYS:
        raise ParseError(
            f"unknown --sort-by {sort_by!r} - choose from {sorted(_SORT_KEYS)}"
        )
    if counter_scope not in ("dir", "global"):
        raise ParseError("--counter-scope must be 'dir' or 'global'")
    now = now or datetime.now()
    ordered = sorted(files, key=_SORT_KEYS[sort_by], reverse=reverse)
    plan = Plan()
    allocator = DestinationAllocator(conflict, sources={info.path for info in files})
    counters: dict[Path, int] = {}
    global_key = Path(".")

    for info in ordered:
        key = global_key if counter_scope == "global" else info.path.parent
        counters[key] = counters.get(key, 0) + 1
        counter = start + (counters[key] - 1) * step
        filename = render_filename(
            pattern, info, counter=counter, project=project, now=now,
            auto_ext=auto_ext, slug=slug, lower=lower,
        )
        candidate = info.path.with_name(filename)
        if candidate == info.path:
            plan.skipped.append(Skipped(info.path, "name already matches"))
            continue
        dest = allocator.allocate(candidate)
        if dest is None:
            plan.skipped.append(Skipped(info.path, f"name taken: {candidate.name}"))
            continue
        plan.actions.append(
            Action(
                kind=RENAME, source=info.path, dest=dest,
                reason=f"pattern {pattern}", size=info.size,
            )
        )
    return plan


def plan_replace(
    files: list[FileInfo],
    find: str,
    replace: str,
    *,
    regex: bool = False,
    conflict: str = CONFLICT_NUMBER,
    slug: bool = False,
    lower: bool = False,
) -> Plan:
    """Find/replace inside filenames - the quick alternative to a full pattern."""
    import re

    plan = Plan()
    allocator = DestinationAllocator(conflict, sources={info.path for info in files})
    try:
        matcher = re.compile(find) if regex else None
    except re.error as exc:
        raise ParseError(f"invalid --regex pattern: {exc}") from exc

    for info in files:
        stem, ext = split_name(info.path)
        new_stem = matcher.sub(replace, stem) if matcher else stem.replace(find, replace)
        if slug:
            from .util import slugify

            new_stem = slugify(new_stem)
        if lower:
            new_stem = new_stem.lower()
        filename = f"{new_stem}.{ext}" if ext else new_stem
        candidate = info.path.with_name(filename)
        if candidate == info.path:
            plan.skipped.append(Skipped(info.path, "no change"))
            continue
        dest = allocator.allocate(candidate)
        if dest is None:
            plan.skipped.append(Skipped(info.path, f"name taken: {candidate.name}"))
            continue
        plan.actions.append(
            Action(
                kind=RENAME, source=info.path, dest=dest,
                reason=f"replace {find!r} -> {replace!r}", size=info.size,
            )
        )
    return plan
