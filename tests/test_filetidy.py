"""Tests for filetidy. Standard library only: python3 -m unittest discover tests"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from filetidy import cli, dedupe, executor, naming, plan as planning, rules, util
from filetidy.categories import category_for
from filetidy.filters import ScanOptions, scan


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="filetidy-test-"))
        self.root = self.tmp / "Downloads"
        self.root.mkdir()
        self.home = self.tmp / "home"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, relative: str, content: str = "x", when: datetime | None = None) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if when:
            stamp = when.timestamp()
            os.utime(path, (stamp, stamp))
        return path

    def tree(self) -> set[str]:
        return {
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        }

    def scan(self, **kwargs) -> list:
        return scan(self.root, ScanOptions(**kwargs))


class UtilTests(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(util.parse_size("10MB"), 10 * 1024 ** 2)
        self.assertEqual(util.parse_size("1.5g"), int(1.5 * 1024 ** 3))
        self.assertEqual(util.parse_size("512"), 512)
        self.assertEqual(util.parse_size(4096), 4096)
        with self.assertRaises(util.ParseError):
            util.parse_size("10furlongs")

    def test_parse_age(self):
        now = datetime(2026, 8, 19, 12, 0, 0)
        self.assertEqual(util.parse_age("7d", now), now - timedelta(days=7))
        self.assertEqual(util.parse_age("2w", now), now - timedelta(days=14))
        self.assertEqual(util.parse_age("2026-01-01", now), datetime(2026, 1, 1))
        with self.assertRaises(util.ParseError):
            util.parse_age("soon", now)

    def test_split_name_handles_dotfiles_and_double_extensions(self):
        self.assertEqual(util.split_name(Path("a.tar.gz")), ("a", "tar.gz"))
        self.assertEqual(util.split_name(Path(".gitignore")), (".gitignore", ""))
        self.assertEqual(util.split_name(Path("README")), ("README", ""))
        self.assertEqual(util.split_name(Path("a.b.pdf")), ("a.b", "pdf"))

    def test_sanitize_component(self):
        self.assertEqual(util.sanitize_component("bad/name?.txt"), "bad_name_.txt")
        self.assertTrue(util.sanitize_component("con").startswith("_"))
        self.assertEqual(util.slugify("Héllo Wörld 12"), "hello-world-12")

    def test_category_lookup(self):
        self.assertEqual(category_for("PDF"), "Documents")
        self.assertEqual(category_for("tar.gz"), "Archives")
        self.assertEqual(category_for(""), "No Extension")
        self.assertEqual(category_for("qqq"), "Other")


class ScanTests(TempDirCase):
    def test_non_recursive_by_default(self):
        self.write("a.pdf")
        self.write("sub/b.pdf")
        self.assertEqual([i.path.name for i in self.scan()], ["a.pdf"])
        names = sorted(i.path.name for i in self.scan(recursive=True))
        self.assertEqual(names, ["a.pdf", "b.pdf"])

    def test_hidden_and_skip_dirs(self):
        self.write(".secret.pdf")
        self.write(".git/config.pdf")
        self.write("visible.pdf")
        self.assertEqual([i.path.name for i in self.scan(recursive=True)], ["visible.pdf"])
        hidden = sorted(i.path.name for i in self.scan(recursive=True, include_hidden=True))
        self.assertEqual(hidden, [".secret.pdf", "visible.pdf"])  # .git stays excluded

    def test_filters(self):
        self.write("big.bin", "x" * 500)
        self.write("small.bin", "x")
        self.write("note.txt", "x")
        self.assertEqual(
            [i.path.name for i in self.scan(min_size=100)], ["big.bin"]
        )
        self.assertEqual(
            [i.path.name for i in self.scan(extensions=["txt"])], ["note.txt"]
        )
        self.assertEqual(
            sorted(i.path.name for i in self.scan(exclude=["*.bin"])), ["note.txt"]
        )
        self.assertEqual(
            sorted(i.path.name for i in self.scan(include=["big*"])), ["big.bin"]
        )

    def test_age_filters(self):
        old = datetime.now() - timedelta(days=100)
        self.write("old.pdf", when=old)
        self.write("new.pdf")
        cutoff = datetime.now() - timedelta(days=30)
        self.assertEqual([i.path.name for i in self.scan(newer_than=cutoff)], ["new.pdf"])
        self.assertEqual([i.path.name for i in self.scan(older_than=cutoff)], ["old.pdf"])

    def test_max_depth(self):
        self.write("a.pdf")
        self.write("one/b.pdf")
        self.write("one/two/c.pdf")
        names = sorted(i.path.name for i in self.scan(recursive=True, max_depth=1))
        self.assertEqual(names, ["a.pdf", "b.pdf"])


class NamingTests(TempDirCase):
    def test_requested_example_pattern(self):
        self.write("scan001.pdf", when=datetime(2026, 8, 3, 9, 0))
        info = self.scan()[0]
        rendered = naming.render_filename(
            "{project}_{date:%Y-%m}-{n:03}", info, counter=1, project="ProjectName"
        )
        self.assertEqual(rendered, "ProjectName_2026-08-001.pdf")

    def test_tokens_and_specs(self):
        self.write("Photo.JPG", "abc", when=datetime(2026, 1, 2, 3, 4))
        info = self.scan()[0]
        self.assertEqual(
            naming.render_filename("{name}-{category}-{ext}", info), "Photo-Images-JPG.JPG"
        )
        self.assertEqual(naming.render_filename("{date}", info), "2026-01-02.JPG")
        self.assertEqual(naming.render_filename("{size}b", info), "3b.JPG")
        self.assertEqual(len(naming.render_filename("{hash}", info)), 8 + 4)

    def test_auto_ext_not_doubled(self):
        self.write("a.pdf")
        info = self.scan()[0]
        self.assertEqual(naming.render_filename("{name}.{ext}", info), "a.pdf")
        self.assertEqual(
            naming.render_filename("{name}", info, auto_ext=False), "a"
        )

    def test_unknown_token_raises(self):
        self.write("a.pdf")
        info = self.scan()[0]
        with self.assertRaises(util.ParseError):
            naming.render_filename("{nope}", info)

    def test_pattern_cannot_escape_into_parent_dirs(self):
        self.write("a.pdf")
        info = self.scan()[0]
        self.assertNotIn("/", naming.render_filename("../{name}", info))


class SortPlanTests(TempDirCase):
    def test_by_type(self):
        self.write("a.pdf")
        self.write("b.png")
        result = planning.plan_sort(self.scan(), self.root, ["type"])
        destinations = {a.dest.relative_to(self.root).as_posix() for a in result.actions}
        self.assertEqual(destinations, {"Documents/a.pdf", "Images/b.png"})

    def test_by_type_and_date(self):
        self.write("a.pdf", when=datetime(2026, 3, 4))
        result = planning.plan_sort(self.scan(), self.root, ["type", "date"])
        self.assertEqual(
            result.actions[0].dest.relative_to(self.root).as_posix(),
            "Documents/2026-03/a.pdf",
        )

    def test_already_in_place_is_skipped(self):
        self.write("Documents/a.pdf")
        result = planning.plan_sort(self.scan(recursive=True), self.root, ["type"])
        self.assertEqual(result.actions, [])
        self.assertEqual(len(result.skipped), 1)

    def test_conflict_policies(self):
        self.write("a.pdf", "one")
        self.write("Documents/a.pdf", "two")
        files = [i for i in self.scan() if i.path.parent == self.root]
        numbered = planning.plan_sort(files, self.root, ["type"], conflict="number")
        self.assertEqual(numbered.actions[0].dest.name, "a (1).pdf")
        skipped = planning.plan_sort(files, self.root, ["type"], conflict="skip")
        self.assertEqual(skipped.actions, [])
        overwrite = planning.plan_sort(files, self.root, ["type"], conflict="overwrite")
        self.assertEqual(overwrite.actions[0].dest.name, "a.pdf")

    def test_two_files_same_target_name_get_numbered(self):
        self.write("x/a.pdf", "one")
        self.write("y/a.pdf", "two")
        result = planning.plan_sort(self.scan(recursive=True), self.root, ["type"])
        names = sorted(a.dest.name for a in result.actions)
        self.assertEqual(names, ["a (1).pdf", "a.pdf"])

    def test_sort_with_rename(self):
        self.write("a.pdf", when=datetime(2026, 8, 1))
        self.write("b.pdf", when=datetime(2026, 8, 2))
        result = planning.plan_sort(
            self.scan(), self.root, ["type"],
            rename_pattern="{project}_{date:%Y-%m}-{n:03}", project="Proj",
        )
        names = sorted(a.dest.name for a in result.actions)
        self.assertEqual(names, ["Proj_2026-08-001.pdf", "Proj_2026-08-002.pdf"])


class RuleTests(TempDirCase):
    def _rules_file(self, body: str) -> Path:
        path = self.tmp / "rules.json"
        path.write_text(body, encoding="utf-8")
        return path

    def test_first_match_wins_and_default_target(self):
        path = self._rules_file(
            '{"rules": ['
            ' {"name": "Invoices", "match": {"name": "*invoice*", "ext": ["pdf"]},'
            '  "target": "Finance/{date:%Y}", "rename": "INV_{n:02}.{ext}"},'
            ' {"name": "Pdfs", "match": {"ext": ["pdf"]}, "target": "Docs"}'
            '], "default_target": "Misc/{category}"}'
        )
        ruleset = rules.load_rules(path)
        self.write("acme invoice.pdf", when=datetime(2026, 5, 1))
        self.write("other.pdf")
        self.write("photo.png")
        result = planning.plan_sort(self.scan(), self.root, ["rules"], ruleset=ruleset)
        mapping = {
            a.source.name: a.dest.relative_to(self.root).as_posix() for a in result.actions
        }
        self.assertEqual(mapping["acme invoice.pdf"], "Finance/2026/INV_01.pdf")
        self.assertEqual(mapping["other.pdf"], "Docs/other.pdf")
        self.assertEqual(mapping["photo.png"], "Misc/Images/photo.png")

    def test_unmatched_files_are_left_alone_without_default(self):
        path = self._rules_file(
            '{"rules": [{"name": "Only exe", "match": {"ext": ["exe"]}, "target": "Apps"}]}'
        )
        ruleset = rules.load_rules(path)
        self.write("doc.pdf")
        result = planning.plan_sort(self.scan(), self.root, ["rules"], ruleset=ruleset)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.skipped[0].reason, "no rule matched")

    def test_size_regex_and_age_matching(self):
        path = self._rules_file(
            '{"rules": [{"name": "Big old screenshots",'
            ' "match": {"regex": "^Screenshot", "min_size": "100", "older_than": "30d"},'
            ' "target": "Old"}]}'
        )
        ruleset = rules.load_rules(path)
        stale = datetime.now() - timedelta(days=60)
        self.write("Screenshot big.png", "x" * 200, when=stale)
        self.write("Screenshot small.png", "x", when=stale)
        self.write("Screenshot new.png", "x" * 200)
        result = planning.plan_sort(self.scan(), self.root, ["rules"], ruleset=ruleset)
        self.assertEqual([a.source.name for a in result.actions], ["Screenshot big.png"])

    def test_bad_rules_are_reported(self):
        with self.assertRaises(util.ParseError):
            rules.load_rules(self._rules_file('{"rules": [{"name": "x"}]}'))
        with self.assertRaises(util.ParseError):
            rules.load_rules(
                self._rules_file('{"rules": [{"target": "a", "match": {"nope": 1}}]}')
            )
        with self.assertRaises(util.ParseError):
            rules.load_rules(self._rules_file('{"nothing": true}'))


class RenamePlanTests(TempDirCase):
    def test_counter_order_and_padding(self):
        self.write("b.pdf", when=datetime(2026, 1, 2))
        self.write("a.pdf", when=datetime(2026, 1, 1))
        by_name = planning.plan_rename(self.scan(), "{n:03}", sort_by="name")
        self.assertEqual([a.dest.name for a in by_name.actions], ["001.pdf", "002.pdf"])
        by_date = planning.plan_rename(self.scan(), "{n:03}", sort_by="date", reverse=True)
        mapping = {a.source.name: a.dest.name for a in by_date.actions}
        self.assertEqual(mapping["b.pdf"], "001.pdf")

    def test_counter_scope(self):
        self.write("x/a.pdf")
        self.write("y/b.pdf")
        files = self.scan(recursive=True)
        per_dir = planning.plan_rename(files, "{n:02}", counter_scope="dir")
        self.assertEqual(sorted(a.dest.name for a in per_dir.actions), ["01.pdf", "01.pdf"])
        globally = planning.plan_rename(files, "{n:02}", counter_scope="global")
        self.assertEqual(sorted(a.dest.name for a in globally.actions), ["01.pdf", "02.pdf"])

    def test_start_and_step(self):
        self.write("a.pdf")
        self.write("b.pdf")
        result = planning.plan_rename(self.scan(), "{n:03}", start=10, step=5)
        self.assertEqual([a.dest.name for a in result.actions], ["010.pdf", "015.pdf"])

    def test_replace_and_regex(self):
        self.write("Draft - report.pdf")
        plain = planning.plan_replace(self.scan(), "Draft - ", "")
        self.assertEqual(plain.actions[0].dest.name, "report.pdf")
        regexed = planning.plan_replace(self.scan(), r"^\w+ - ", "final-", regex=True)
        self.assertEqual(regexed.actions[0].dest.name, "final-report.pdf")

    def test_slug_and_lower(self):
        self.write("Héllo Wörld.PDF")
        result = planning.plan_rename(self.scan(), "{name}", slug=True)
        self.assertEqual(result.actions[0].dest.name, "hello-world.pdf")


class DedupeTests(TempDirCase):
    def test_detects_identical_content_regardless_of_name(self):
        self.write("a.pdf", "same content")
        self.write("nested/b.pdf", "same content")
        self.write("c.pdf", "different")
        groups = dedupe.find_duplicates(self.scan(recursive=True))
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            sorted(i.path.name for i in groups[0].files), ["a.pdf", "b.pdf"]
        )

    def test_same_size_different_content_is_not_a_duplicate(self):
        self.write("a.bin", "aaaa")
        self.write("b.bin", "bbbb")
        self.assertEqual(dedupe.find_duplicates(self.scan()), [])

    def test_empty_files_ignored_unless_requested(self):
        self.write("a.txt", "")
        self.write("b.txt", "")
        self.assertEqual(dedupe.find_duplicates(self.scan()), [])
        self.assertEqual(len(dedupe.find_duplicates(self.scan(), min_size=0)), 1)

    def test_keep_policies(self):
        old = datetime.now() - timedelta(days=10)
        self.write("longer-name.pdf", "dupe", when=old)
        self.write("s.pdf", "dupe")
        groups = dedupe.find_duplicates(self.scan())
        oldest = dedupe.plan_dedupe(groups, action="delete", keep="oldest")
        self.assertEqual(oldest.actions[0].source.name, "s.pdf")
        newest = dedupe.plan_dedupe(groups, action="delete", keep="newest")
        self.assertEqual(newest.actions[0].source.name, "longer-name.pdf")
        shortest = dedupe.plan_dedupe(groups, action="delete", keep="shortest-name")
        self.assertEqual(shortest.actions[0].source.name, "longer-name.pdf")

    def test_report_action_plans_nothing(self):
        self.write("a.pdf", "dupe")
        self.write("b.pdf", "dupe")
        groups = dedupe.find_duplicates(self.scan())
        self.assertEqual(dedupe.plan_dedupe(groups, action="report").actions, [])

    def test_quarantine_keeps_relative_layout(self):
        self.write("a.pdf", "dupe")
        self.write("nested/a.pdf", "dupe")
        groups = dedupe.find_duplicates(self.scan(recursive=True))
        quarantine = self.root / "_dupes"
        result = dedupe.plan_dedupe(
            groups, action="move", keep="shallowest", quarantine=quarantine
        )
        self.assertEqual(
            result.actions[0].dest.relative_to(quarantine).as_posix(), "nested/a.pdf"
        )


class ExecutorTests(TempDirCase):
    def test_apply_then_undo_restores_everything(self):
        self.write("a.pdf")
        self.write("b.png")
        result = planning.plan_sort(self.scan(), self.root, ["type"])
        run = executor.execute(result, base=self.home)
        self.assertTrue(run.ok)
        self.assertEqual(self.tree(), {"Documents/a.pdf", "Images/b.png"})

        undone = executor.undo(run.journal, dry_run=False)
        self.assertEqual(undone.restored, 2)
        self.assertEqual(self.tree(), {"a.pdf", "b.png"})
        self.assertFalse((self.root / "Documents").exists())

    def test_undo_dry_run_changes_nothing(self):
        self.write("a.pdf")
        run = executor.execute(
            planning.plan_sort(self.scan(), self.root, ["type"]), base=self.home
        )
        before = self.tree()
        preview = executor.undo(run.journal, dry_run=True)
        self.assertEqual(preview.restored, 1)
        self.assertEqual(self.tree(), before)

    def test_rename_swap_does_not_lose_files(self):
        self.write("a.txt", "content-a")
        self.write("b.txt", "content-b")
        swap = planning.Plan(
            actions=[
                planning.Action(planning.RENAME, self.root / "a.txt", self.root / "b.txt"),
                planning.Action(planning.RENAME, self.root / "b.txt", self.root / "a.txt"),
            ],
            root=self.root,
        )
        run = executor.execute(swap, base=self.home)
        self.assertTrue(run.ok, run.failed)
        self.assertEqual((self.root / "a.txt").read_text(), "content-b")
        self.assertEqual((self.root / "b.txt").read_text(), "content-a")
        self.assertFalse(list(self.root.glob(f"{executor.TEMP_PREFIX}*")))

    def test_shifting_chain_of_renames(self):
        for name in ("1.txt", "2.txt", "3.txt"):
            self.write(name, name)
        chain = planning.Plan(
            actions=[
                planning.Action(planning.RENAME, self.root / "1.txt", self.root / "2.txt"),
                planning.Action(planning.RENAME, self.root / "2.txt", self.root / "3.txt"),
                planning.Action(planning.RENAME, self.root / "3.txt", self.root / "4.txt"),
            ],
            root=self.root,
        )
        run = executor.execute(chain, base=self.home)
        self.assertTrue(run.ok, run.failed)
        self.assertEqual((self.root / "2.txt").read_text(), "1.txt")
        self.assertEqual((self.root / "3.txt").read_text(), "2.txt")
        self.assertEqual((self.root / "4.txt").read_text(), "3.txt")

    def test_delete_goes_to_trash_and_can_be_restored(self):
        self.write("dupe.pdf", "x")
        delete_plan = planning.Plan(
            actions=[planning.Action(planning.DELETE, self.root / "dupe.pdf", None)],
            root=self.root,
        )
        run = executor.execute(delete_plan, base=self.home)
        self.assertFalse((self.root / "dupe.pdf").exists())
        self.assertTrue(run.trash_dir.exists())
        executor.undo(run.journal, dry_run=False)
        self.assertTrue((self.root / "dupe.pdf").exists())

    def test_hard_delete_is_reported_as_unrecoverable(self):
        self.write("gone.pdf", "x")
        delete_plan = planning.Plan(
            actions=[planning.Action(planning.DELETE, self.root / "gone.pdf", None)],
            root=self.root,
        )
        run = executor.execute(delete_plan, base=self.home, hard_delete=True)
        undone = executor.undo(run.journal, dry_run=False)
        self.assertEqual(undone.unrecoverable, [str(self.root / "gone.pdf")])

    def test_overwrite_keeps_the_displaced_file_in_trash(self):
        self.write("a.pdf", "new")
        self.write("Documents/a.pdf", "old")
        files = [i for i in self.scan() if i.path.parent == self.root]
        overwrite = planning.plan_sort(files, self.root, ["type"], conflict="overwrite")
        run = executor.execute(overwrite, base=self.home)
        self.assertEqual((self.root / "Documents" / "a.pdf").read_text(), "new")
        self.assertTrue(any(p.read_text() == "old" for p in run.trash_dir.rglob("*.pdf")))

    def test_journal_is_optional(self):
        self.write("a.pdf")
        run = executor.execute(
            planning.plan_sort(self.scan(), self.root, ["type"]),
            base=self.home, write_journal=False,
        )
        self.assertIsNone(run.journal)
        self.assertEqual(executor.list_journals(self.home), [])


class CliTests(TempDirCase):
    def run_cli(self, *argv: str) -> int:
        return cli.main([*argv, "--home", str(self.home)])

    def test_dry_run_is_the_default(self):
        self.write("a.pdf")
        self.assertEqual(self.run_cli("sort", str(self.root), "--by", "type", "--quiet"), 0)
        self.assertEqual(self.tree(), {"a.pdf"})

    def test_apply_moves_files(self):
        self.write("a.pdf")
        self.assertEqual(
            self.run_cli("sort", str(self.root), "--by", "type", "--apply", "-y", "--quiet"), 0
        )
        self.assertEqual(self.tree(), {"Documents/a.pdf"})

    def test_rename_end_to_end(self):
        self.write("scan.pdf", when=datetime(2026, 8, 3))
        self.run_cli(
            "rename", str(self.root), "--pattern", "{project}_{date:%Y-%m}-{n:03}",
            "--project", "ProjectName", "--apply", "-y", "--quiet",
        )
        self.assertEqual(self.tree(), {"ProjectName_2026-08-001.pdf"})

    def test_dedupe_move_end_to_end(self):
        self.write("a.pdf", "same")
        self.write("b.pdf", "same")
        self.run_cli(
            "dedupe", str(self.root), "--action", "move", "--keep", "first",
            "--apply", "-y", "--quiet",
        )
        self.assertEqual(self.tree(), {"a.pdf", "_duplicates/b.pdf"})

    def test_undo_via_cli(self):
        self.write("a.pdf")
        self.run_cli("sort", str(self.root), "--by", "type", "--apply", "-y", "--quiet")
        self.run_cli("undo", "--apply")
        self.assertEqual(self.tree(), {"a.pdf"})

    def test_dest_option_writes_elsewhere(self):
        self.write("a.pdf")
        other = self.tmp / "Sorted"
        other.mkdir()
        self.run_cli(
            "sort", str(self.root), "--by", "type", "--dest", str(other),
            "--apply", "-y", "--quiet",
        )
        self.assertEqual(self.tree(), set())
        self.assertTrue((other / "Documents" / "a.pdf").exists())

    def test_missing_directory_exits_with_code_two(self):
        self.assertEqual(self.run_cli("sort", str(self.tmp / "nope"), "--quiet"), 2)

    def test_bad_by_value_exits_with_code_two(self):
        self.assertEqual(self.run_cli("sort", str(self.root), "--by", "colour"), 2)

    def test_rules_flag_required_for_rules_mode(self):
        self.assertEqual(self.run_cli("sort", str(self.root), "--by", "rules"), 2)

    def test_pattern_and_replace_are_mutually_exclusive(self):
        self.assertEqual(
            self.run_cli("rename", str(self.root), "--pattern", "{n}", "--replace", "x"), 2
        )

    def test_info_and_history_run(self):
        self.assertEqual(cli.main(["info"]), 0)
        self.assertEqual(self.run_cli("history"), 0)


if __name__ == "__main__":
    unittest.main()
