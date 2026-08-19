"""Custom sorting rules loaded from a YAML or JSON file.

    rules:
      - name: Invoices
        match:
          name: "*invoice*"          # glob, case-insensitive
          ext: [pdf, png]
          regex: "^INV-[0-9]+"       # matched against the filename
          min_size: 10KB
          max_size: 20MB
          older_than: 30d            # modified before now-30d
          newer_than: 2026-01-01
        target: "Finance/Invoices/{date:%Y}"
        rename: "Invoice_{date:%Y-%m-%d}_{n:03}.{ext}"   # optional
    default_target: "Unsorted/{category}"                # optional

First matching rule wins. YAML needs PyYAML; JSON always works.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .filters import FileInfo
from .util import ParseError, parse_age, parse_size

_MATCH_KEYS = {
    "name", "path", "ext", "regex", "min_size", "max_size",
    "older_than", "newer_than", "category",
}


@dataclass
class Rule:
    name: str
    target: str
    globs: list[str] = field(default_factory=list)
    path_globs: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    regex: re.Pattern[str] | None = None
    categories: list[str] = field(default_factory=list)
    min_size: int | None = None
    max_size: int | None = None
    older_than: datetime | None = None
    newer_than: datetime | None = None
    rename: str | None = None

    def matches(self, info: FileInfo) -> bool:
        from .categories import category_for

        name = info.path.name.lower()
        if self.globs and not any(fnmatch.fnmatch(name, g.lower()) for g in self.globs):
            return False
        if self.path_globs:
            rel = info.relative.as_posix().lower()
            if not any(fnmatch.fnmatch(rel, g.lower()) for g in self.path_globs):
                return False
        if self.extensions and info.ext.lower() not in self.extensions:
            return False
        if self.regex and not self.regex.search(info.path.name):
            return False
        if self.categories and category_for(info.ext).lower() not in self.categories:
            return False
        if self.min_size is not None and info.size < self.min_size:
            return False
        if self.max_size is not None and info.size > self.max_size:
            return False
        if self.older_than is not None and info.modified > self.older_than:
            return False
        if self.newer_than is not None and info.modified < self.newer_than:
            return False
        return True


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)
    default_target: str | None = None

    def match(self, info: FileInfo) -> Rule | None:
        for rule in self.rules:
            if rule.matches(info):
                return rule
        return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise ParseError(f"expected a string or list, got {value!r}")


def _load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ParseError(
                f"{path} is YAML but PyYAML is not installed - "
                "install pyyaml or use a .json rules file"
            ) from exc
        document = yaml.safe_load(text)
    else:
        document = json.loads(text)
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ParseError(f"{path}: top level must be a mapping")
    return document


def parse_rule(raw: dict[str, Any], index: int, now: datetime | None = None) -> Rule:
    if not isinstance(raw, dict):
        raise ParseError(f"rule #{index + 1}: expected a mapping, got {raw!r}")
    name = str(raw.get("name") or f"rule-{index + 1}")
    target = raw.get("target")
    if not target:
        raise ParseError(f"rule {name!r}: 'target' is required")
    match = raw.get("match") or {}
    if not isinstance(match, dict):
        raise ParseError(f"rule {name!r}: 'match' must be a mapping")
    unknown = set(match) - _MATCH_KEYS
    if unknown:
        raise ParseError(
            f"rule {name!r}: unknown match keys {sorted(unknown)} - "
            f"supported: {sorted(_MATCH_KEYS)}"
        )
    try:
        regex = re.compile(match["regex"]) if match.get("regex") else None
    except re.error as exc:
        raise ParseError(f"rule {name!r}: invalid regex - {exc}") from exc
    return Rule(
        name=name,
        target=str(target),
        globs=_as_list(match.get("name")),
        path_globs=_as_list(match.get("path")),
        extensions=[e.lower().lstrip(".") for e in _as_list(match.get("ext"))],
        regex=regex,
        categories=[c.lower() for c in _as_list(match.get("category"))],
        min_size=parse_size(match["min_size"]) if match.get("min_size") else None,
        max_size=parse_size(match["max_size"]) if match.get("max_size") else None,
        older_than=parse_age(match["older_than"], now) if match.get("older_than") else None,
        newer_than=parse_age(match["newer_than"], now) if match.get("newer_than") else None,
        rename=str(raw["rename"]) if raw.get("rename") else None,
    )


def load_rules(path: Path, now: datetime | None = None) -> RuleSet:
    document = _load_document(path)
    raw_rules = document.get("rules")
    if raw_rules is None:
        raise ParseError(f"{path}: no 'rules' key found")
    if not isinstance(raw_rules, list):
        raise ParseError(f"{path}: 'rules' must be a list")
    rules = [parse_rule(raw, index, now) for index, raw in enumerate(raw_rules)]
    default_target = document.get("default_target")
    return RuleSet(rules=rules, default_target=str(default_target) if default_target else None)
