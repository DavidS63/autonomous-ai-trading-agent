"""Duplicate detection by content, not by name.

Cheap checks first: group by size, then by a 64 KB fingerprint, then by a full
hash. Files that are unique in size are never opened at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .filters import FileInfo
from .hashing import file_hash, quick_hash
from .plan import DELETE, MOVE, Action, DestinationAllocator, Plan, Skipped
from .util import ParseError, human_size

KEEP_POLICIES = ("oldest", "newest", "shortest-name", "longest-name", "shallowest", "first")


@dataclass
class DuplicateGroup:
    digest: str
    size: int
    files: list[FileInfo] = field(default_factory=list)

    @property
    def wasted_bytes(self) -> int:
        return self.size * max(0, len(self.files) - 1)


def _keep_key(policy: str):
    if policy == "oldest":
        return lambda info: (info.modified, str(info.path).lower())
    if policy == "newest":
        return lambda info: (-info.modified.timestamp(), str(info.path).lower())
    if policy == "shortest-name":
        return lambda info: (len(info.path.name), str(info.path).lower())
    if policy == "longest-name":
        return lambda info: (-len(info.path.name), str(info.path).lower())
    if policy == "shallowest":
        return lambda info: (len(info.relative.parts), str(info.path).lower())
    if policy == "first":
        return lambda info: str(info.path).lower()
    raise ParseError(f"unknown --keep policy: {policy!r} (choose from {KEEP_POLICIES})")


def find_duplicates(
    files: list[FileInfo], algorithm: str = "blake2b", min_size: int = 1
) -> list[DuplicateGroup]:
    """Group files with byte-identical content. Empty files are ignored by default."""
    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for info in files:
        if info.size >= min_size:
            by_size[info.size].append(info)

    groups: list[DuplicateGroup] = []
    for size, candidates in sorted(by_size.items()):
        if len(candidates) < 2:
            continue
        by_quick: dict[str, list[FileInfo]] = defaultdict(list)
        for info in candidates:
            try:
                by_quick[quick_hash(info.path, algorithm)].append(info)
            except OSError:
                continue
        for quick_group in by_quick.values():
            if len(quick_group) < 2:
                continue
            by_full: dict[str, list[FileInfo]] = defaultdict(list)
            for info in quick_group:
                try:
                    by_full[file_hash(info.path, algorithm)].append(info)
                except OSError:
                    continue
            for digest, full_group in by_full.items():
                if len(full_group) > 1:
                    groups.append(
                        DuplicateGroup(
                            digest=digest,
                            size=size,
                            files=sorted(full_group, key=lambda i: str(i.path).lower()),
                        )
                    )
    groups.sort(key=lambda group: group.wasted_bytes, reverse=True)
    return groups


def plan_dedupe(
    groups: list[DuplicateGroup],
    action: str = "report",
    keep: str = "oldest",
    quarantine: Path | None = None,
    conflict: str = "number",
) -> Plan:
    """Turn duplicate groups into delete/move actions for everything but the keeper."""
    if action not in ("report", "delete", "move"):
        raise ParseError(f"unknown dedupe action: {action!r}")
    plan = Plan()
    key = _keep_key(keep)
    allocator = DestinationAllocator(conflict)

    for group in groups:
        ordered = sorted(group.files, key=key)
        keeper, losers = ordered[0], ordered[1:]
        plan.skipped.append(
            Skipped(keeper.path, f"kept ({keep}); {len(losers)} duplicate(s)")
        )
        for loser in losers:
            reason = f"duplicate of {keeper.path.name} [{group.digest[:8]}]"
            if action == "report":
                plan.skipped.append(Skipped(loser.path, reason))
                continue
            if action == "delete":
                plan.actions.append(
                    Action(kind=DELETE, source=loser.path, dest=None,
                           reason=reason, size=loser.size)
                )
                continue
            assert quarantine is not None
            candidate = quarantine / loser.relative
            dest = allocator.allocate(candidate)
            if dest is None:
                plan.skipped.append(Skipped(loser.path, "quarantine slot taken"))
                continue
            plan.actions.append(
                Action(kind=MOVE, source=loser.path, dest=dest,
                       reason=reason, size=loser.size)
            )
    return plan


def summarize(groups: list[DuplicateGroup]) -> str:
    wasted = sum(group.wasted_bytes for group in groups)
    copies = sum(len(group.files) - 1 for group in groups)
    return (
        f"{len(groups)} duplicate group(s), {copies} redundant copy(ies), "
        f"{human_size(wasted)} reclaimable"
    )
