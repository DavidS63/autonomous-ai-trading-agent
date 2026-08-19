"""Command line interface for filetidy.

    tidy sort ~/Downloads --by type,date --apply
    tidy rename ./scans --pattern "{project}_{date:%Y-%m}-{n:03}" --project Roadmap --apply
    tidy dedupe ~/Downloads --action move --keep oldest --apply
    tidy undo

Every command previews by default; nothing touches disk without --apply.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .categories import CATEGORIES
from .dedupe import KEEP_POLICIES, find_duplicates, plan_dedupe, summarize
from .executor import (
    describe_journal,
    execute,
    list_journals,
    undo,
)
from .filters import ScanOptions, scan
from .naming import KNOWN_TOKENS
from .plan import CONFLICT_POLICIES, Plan, plan_rename, plan_replace, plan_sort
from .rules import RuleSet, load_rules
from .util import ParseError, human_size, is_within, parse_age, parse_size

SORT_COMPONENTS = ("type", "date", "ext", "rules")


# ------------------------------------------------------------------ arg plumbing


def add_scan_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("file selection")
    group.add_argument("-r", "--recursive", action="store_true",
                       help="descend into subfolders (default: top level only)")
    group.add_argument("--max-depth", type=int, metavar="N",
                       help="limit recursion depth")
    group.add_argument("--include", action="append", default=[], metavar="GLOB",
                       help="only files matching this glob (repeatable)")
    group.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                       help="skip files matching this glob (repeatable)")
    group.add_argument("--ext", action="append", default=[], metavar="EXT",
                       help="only these extensions, e.g. --ext pdf --ext jpg")
    group.add_argument("--min-size", metavar="SIZE", help="e.g. 10MB")
    group.add_argument("--max-size", metavar="SIZE", help="e.g. 2GB")
    group.add_argument("--newer-than", metavar="AGE",
                       help="modified within this window, e.g. 7d or 2026-01-01")
    group.add_argument("--older-than", metavar="AGE",
                       help="modified before this point, e.g. 90d")
    group.add_argument("--hidden", action="store_true", help="include hidden files")
    group.add_argument("--follow-symlinks", action="store_true",
                       help="follow symlinked files and folders")


def add_execution_arguments(parser: argparse.ArgumentParser, conflict: bool = True) -> None:
    group = parser.add_argument_group("execution")
    group.add_argument("--apply", action="store_true",
                       help="actually perform the changes (default is a preview)")
    group.add_argument("--dry-run", action="store_true",
                       help="explicitly preview only (the default)")
    group.add_argument("-y", "--yes", action="store_true",
                       help="skip the confirmation prompt when using --apply")
    group.add_argument("--quiet", action="store_true", help="only print the summary")
    group.add_argument("--no-journal", action="store_true",
                       help="do not write an undo journal for this run")
    group.add_argument("--home", metavar="DIR",
                       help="where journals and trash live (default: ~/.filetidy)")
    if conflict:
        group.add_argument("--on-conflict", choices=CONFLICT_POLICIES, default="number",
                           help="what to do when the destination name is taken "
                                "(default: number)")


def build_scan_options(args: argparse.Namespace, now: datetime) -> ScanOptions:
    return ScanOptions(
        recursive=args.recursive or args.max_depth is not None,
        max_depth=args.max_depth,
        include=list(args.include),
        exclude=list(args.exclude),
        extensions=list(args.ext),
        include_hidden=args.hidden,
        min_size=parse_size(args.min_size) if args.min_size else None,
        max_size=parse_size(args.max_size) if args.max_size else None,
        newer_than=parse_age(args.newer_than, now) if args.newer_than else None,
        older_than=parse_age(args.older_than, now) if args.older_than else None,
        follow_symlinks=args.follow_symlinks,
    )


# ---------------------------------------------------------------------- reporting


def print_plan(
    plan: Plan, args: argparse.Namespace, title: str, base: Path | None = None
) -> None:
    verbose = not args.quiet
    if verbose:
        print(f"\n{title}")
        print("-" * len(title))
        if not plan.actions:
            print("Nothing to do.")
        for action in plan.actions:
            print(action.describe(base))
        if plan.skipped and getattr(args, "show_skipped", False):
            print("\nSkipped:")
            for item in plan.skipped:
                print(f"  {_relative(item.path, base)}  ({item.reason})")
    counts = plan.counts()
    parts = [f"{count} {kind}" for kind, count in sorted(counts.items())] or ["0 actions"]
    print(
        f"\n{', '.join(parts)}; {len(plan.skipped)} skipped; "
        f"{human_size(plan.bytes_touched)} affected"
    )


def _relative(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return str(path)


def confirm(plan: Plan, args: argparse.Namespace) -> bool:
    if args.yes or not sys.stdin.isatty():
        return True
    answer = input(f"Apply {len(plan.actions)} change(s)? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def run_plan(
    plan: Plan, args: argparse.Namespace, command: str, base: Path | None = None
) -> int:
    """Preview or apply, then report. Returns the process exit code."""
    title = "Planned changes" if not args.apply else "Applying changes"
    print_plan(plan, args, title, base)
    if not plan.actions:
        return 0
    if not args.apply or args.dry_run:
        print("\nPreview only - re-run with --apply to make these changes.")
        return 0
    if not confirm(plan, args):
        print("Aborted.")
        return 1

    base = Path(args.home).expanduser() if args.home else None
    result = execute(
        plan, command=command, base=base,
        hard_delete=getattr(args, "hard_delete", False),
        write_journal=not args.no_journal,
    )
    print(f"\nApplied {len(result.applied)} change(s).")
    if result.trash_dir:
        print(f"Removed files are in {result.trash_dir}")
    if result.journal:
        print(f"Undo with: tidy undo   (journal: {result.journal})")
    for action, error in result.failed:
        print(f"FAILED  {action.source}: {error}", file=sys.stderr)
    return 0 if result.ok else 1


def load_ruleset(args: argparse.Namespace, now: datetime) -> RuleSet | None:
    if not getattr(args, "rules", None):
        return None
    path = Path(args.rules).expanduser()
    if not path.is_file():
        raise ParseError(f"rules file not found: {path}")
    return load_rules(path, now)


# ----------------------------------------------------------------------- commands


def cmd_sort(args: argparse.Namespace) -> int:
    now = datetime.now()
    root = Path(args.directory).expanduser().resolve()
    components = [c.strip().lower() for c in args.by.split(",") if c.strip()]
    for component in components:
        if component not in SORT_COMPONENTS:
            raise ParseError(
                f"unknown --by value {component!r}; choose from {', '.join(SORT_COMPONENTS)}"
            )
    ruleset = load_ruleset(args, now)
    if "rules" in components and ruleset is None:
        raise ParseError("--by rules needs a --rules FILE")

    files = scan(root, build_scan_options(args, now))
    dest_root = Path(args.dest).expanduser().resolve() if args.dest else root
    plan = plan_sort(
        files, dest_root, components,
        ruleset=ruleset,
        date_format=args.date_format,
        date_source=args.date_source,
        rename_pattern=args.rename,
        project=args.project,
        conflict=args.on_conflict,
        now=now,
    )
    print(f"Scanned {len(files)} file(s) in {root}")
    return run_plan(plan, args, f"sort --by {args.by}", base=root)


def cmd_rename(args: argparse.Namespace) -> int:
    now = datetime.now()
    root = Path(args.directory).expanduser().resolve()
    if bool(args.pattern) == bool(args.replace is not None):
        raise ParseError("provide either --pattern or --replace/--with, not both")

    files = scan(root, build_scan_options(args, now))
    if args.pattern:
        plan = plan_rename(
            files, args.pattern,
            project=args.project or root.name,
            sort_by=args.sort_by,
            reverse=args.reverse,
            start=args.start,
            step=args.step,
            counter_scope=args.counter_scope,
            conflict=args.on_conflict,
            auto_ext=not args.no_auto_ext,
            slug=args.slug,
            lower=args.lower,
            now=now,
        )
        command = f"rename --pattern {args.pattern!r}"
    else:
        plan = plan_replace(
            files, args.replace, args.with_ or "",
            regex=args.regex,
            conflict=args.on_conflict,
            slug=args.slug,
            lower=args.lower,
        )
        command = f"rename --replace {args.replace!r}"
    print(f"Scanned {len(files)} file(s) in {root}")
    return run_plan(plan, args, command, base=root)


def cmd_dedupe(args: argparse.Namespace) -> int:
    now = datetime.now()
    root = Path(args.directory).expanduser().resolve()
    options = build_scan_options(args, now)
    options.recursive = True if not args.no_recursive else options.recursive
    quarantine = (
        Path(args.quarantine).expanduser().resolve()
        if args.quarantine
        else root / "_duplicates"
    )
    # Never let an earlier quarantine run pollute this one.
    files = [
        info for info in scan(root, options) if not is_within(info.path, quarantine)
    ]
    groups = find_duplicates(
        files, algorithm=args.algorithm,
        min_size=0 if args.include_empty else 1,
    )
    print(f"Scanned {len(files)} file(s) in {root}")
    print(summarize(groups))

    if not args.quiet:
        for group in groups:
            print(f"\n  {human_size(group.size)}  [{group.digest[:12]}]")
            for info in group.files:
                print(f"    {info.relative.as_posix()}")

    plan = plan_dedupe(
        groups, action=args.action, keep=args.keep,
        quarantine=quarantine, conflict=args.on_conflict,
    )
    if args.action == "report":
        print("\nReport only - use --action move or --action delete to clean up.")
        return 0
    args.show_skipped = False
    return run_plan(
        plan, args, f"dedupe --action {args.action} --keep {args.keep}", base=root
    )


def cmd_undo(args: argparse.Namespace) -> int:
    base = Path(args.home).expanduser() if args.home else None
    if args.journal:
        journal_path = Path(args.journal).expanduser()
        if not journal_path.is_file():
            raise ParseError(f"journal not found: {journal_path}")
    else:
        journals = list_journals(base)
        if not journals:
            print("No runs to undo.")
            return 0
        if args.index > len(journals):
            raise ParseError(f"only {len(journals)} run(s) recorded")
        journal_path = journals[-args.index]

    print(f"Undoing {journal_path.name}")
    result = undo(journal_path, dry_run=not args.apply)
    verb = "Would restore" if not args.apply else "Restored"
    print(f"{verb} {result.restored} file(s); removed {result.removed_dirs} empty folder(s)")
    for path, reason in result.failed:
        print(f"  skipped {path}: {reason}", file=sys.stderr)
    for path in result.unrecoverable:
        print(f"  cannot restore (hard deleted): {path}", file=sys.stderr)
    if not args.apply:
        print("\nPreview only - re-run with --apply to restore.")
    elif result.restored:
        journal_path.rename(journal_path.with_suffix(".jsonl.undone"))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    base = Path(args.home).expanduser() if args.home else None
    journals = list_journals(base, include_undone=True)
    if not journals:
        print("No runs recorded yet.")
        return 0
    for path in journals[-args.limit:]:
        print(describe_journal(path))
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    print(f"filetidy {__version__} - local only, no network access\n")
    print("Rename / target tokens:")
    print("  " + ", ".join(f"{{{token}}}" for token in KNOWN_TOKENS))
    print("\n  Dates take strftime specs: {date:%Y-%m-%d}, {created:%Y}, {now:%H%M}")
    print("  Counters take width specs:  {n:03} -> 001")
    print("\nCategories used by --by type:")
    for category, extensions in CATEGORIES.items():
        print(f"  {category:<14} {', '.join(extensions[:10])}"
              + (" ..." if len(extensions) > 10 else ""))
    print(f"  {'Other':<14} everything else")
    print(f"\nKeep policies for dedupe: {', '.join(KEEP_POLICIES)}")
    return 0


# ------------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidy",
        description="Sort, rename and de-duplicate folders. Local only, no APIs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  tidy sort ~/Downloads --by type\n"
            "  tidy sort ~/Downloads --by type,date --date-format %Y-%m --apply\n"
            "  tidy sort ~/Downloads --by rules --rules rules.yaml --apply\n"
            "  tidy rename ./scans --pattern '{project}_{date:%Y-%m}-{n:03}' "
            "--project ProjectName --apply\n"
            "  tidy dedupe ~/Downloads --action move --keep oldest --apply\n"
            "  tidy undo --apply\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"filetidy {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # sort ---------------------------------------------------------------
    sort_parser = subparsers.add_parser(
        "sort", help="move files into folders by type, date, extension or custom rules"
    )
    sort_parser.add_argument("directory", help="folder to organize")
    sort_parser.add_argument(
        "--by", default="type",
        help="comma-separated: type, date, ext, rules (default: type). "
             "e.g. --by type,date nests date folders inside category folders",
    )
    sort_parser.add_argument("--dest", help="write into this folder instead of in place")
    sort_parser.add_argument("--rules", help="YAML/JSON rules file (needed for --by rules)")
    sort_parser.add_argument("--date-format", default="%Y-%m",
                             help="strftime folder format for --by date (default: %%Y-%%m)")
    sort_parser.add_argument("--date-source", choices=("modified", "created"),
                             default="modified", help="which timestamp --by date uses")
    sort_parser.add_argument("--rename", metavar="PATTERN",
                             help="also rename files as they are sorted")
    sort_parser.add_argument("--project", help="value for the {project} token")
    sort_parser.add_argument("--show-skipped", action="store_true",
                             help="list files that were left alone")
    add_scan_arguments(sort_parser)
    add_execution_arguments(sort_parser)
    sort_parser.set_defaults(func=cmd_sort)

    # rename -------------------------------------------------------------
    rename_parser = subparsers.add_parser(
        "rename", help="rename files in place from a pattern or a find/replace"
    )
    rename_parser.add_argument("directory", help="folder containing the files")
    rename_parser.add_argument(
        "-p", "--pattern",
        help="name pattern, e.g. '{project}_{date:%%Y-%%m}-{n:03}' -> "
             "ProjectName_2026-08-001.pdf",
    )
    rename_parser.add_argument("--replace", metavar="FIND",
                               help="text (or regex with --regex) to replace in names")
    rename_parser.add_argument("--with", dest="with_", metavar="TEXT", default="",
                               help="replacement text for --replace")
    rename_parser.add_argument("--regex", action="store_true",
                               help="treat --replace as a regular expression")
    rename_parser.add_argument("--project", help="value for the {project} token")
    rename_parser.add_argument("--sort-by", default="name",
                               choices=("name", "path", "date", "created", "size", "ext"),
                               help="order that decides the {n} counter (default: name)")
    rename_parser.add_argument("--reverse", action="store_true", help="reverse that order")
    rename_parser.add_argument("--start", type=int, default=1, help="counter start (default: 1)")
    rename_parser.add_argument("--step", type=int, default=1, help="counter step (default: 1)")
    rename_parser.add_argument("--counter-scope", choices=("dir", "global"), default="dir",
                               help="restart {n} per folder or run once globally")
    rename_parser.add_argument("--no-auto-ext", action="store_true",
                               help="do not append the original extension automatically")
    rename_parser.add_argument("--slug", action="store_true",
                               help="slugify the result (ascii, lowercase, dashes)")
    rename_parser.add_argument("--lower", action="store_true", help="lowercase the result")
    rename_parser.add_argument("--show-skipped", action="store_true",
                               help="list files that were left alone")
    add_scan_arguments(rename_parser)
    add_execution_arguments(rename_parser)
    rename_parser.set_defaults(func=cmd_rename)

    # dedupe -------------------------------------------------------------
    dedupe_parser = subparsers.add_parser(
        "dedupe", help="find byte-identical files and remove the extra copies"
    )
    dedupe_parser.add_argument("directory", help="folder to inspect (recursive by default)")
    dedupe_parser.add_argument("--action", choices=("report", "move", "delete"),
                               default="report", help="what to do with extra copies")
    dedupe_parser.add_argument("--keep", choices=KEEP_POLICIES, default="oldest",
                               help="which copy survives (default: oldest)")
    dedupe_parser.add_argument("--quarantine", metavar="DIR",
                               help="where --action move puts duplicates "
                                    "(default: <directory>/_duplicates)")
    dedupe_parser.add_argument("--algorithm", default="blake2b",
                               help="hash algorithm (default: blake2b)")
    dedupe_parser.add_argument("--include-empty", action="store_true",
                               help="treat zero-byte files as duplicates of each other")
    dedupe_parser.add_argument("--hard-delete", action="store_true",
                               help="really delete instead of moving to trash (no undo)")
    dedupe_parser.add_argument("--no-recursive", action="store_true",
                               help="only inspect the top level")
    add_scan_arguments(dedupe_parser)
    add_execution_arguments(dedupe_parser)
    dedupe_parser.set_defaults(func=cmd_dedupe)

    # undo / history / info ----------------------------------------------
    undo_parser = subparsers.add_parser("undo", help="revert a previous run")
    undo_parser.add_argument("--journal", help="undo this specific journal file")
    undo_parser.add_argument("--index", type=int, default=1, metavar="N",
                             help="undo the Nth most recent run (default: 1)")
    undo_parser.add_argument("--apply", action="store_true",
                             help="actually restore (default is a preview)")
    undo_parser.add_argument("--home", metavar="DIR", help="filetidy home (default: ~/.filetidy)")
    undo_parser.set_defaults(func=cmd_undo)

    history_parser = subparsers.add_parser("history", help="list previous runs")
    history_parser.add_argument("--limit", type=int, default=10, help="how many to show")
    history_parser.add_argument("--home", metavar="DIR", help="filetidy home")
    history_parser.set_defaults(func=cmd_history)

    info_parser = subparsers.add_parser("info", help="show tokens, categories and policies")
    info_parser.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
