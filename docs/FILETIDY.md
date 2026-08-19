# filetidy - `tidy`

A CLI that organizes a Downloads or project folder: sorts files by type, date,
extension or your own rules; renames them from a pattern; and removes duplicate
copies. It is pure Python standard library - **no external APIs, no network
access, no third-party packages** (PyYAML only if you write rules in YAML rather
than JSON).

```
python tidy.py sort ~/Downloads --by type
```

## Safety model

Three things make it hard to lose a file:

1. **Every command previews by default.** Nothing touches disk until you add
   `--apply`. `--apply` prompts for confirmation on a terminal; add `-y` to skip
   the prompt (non-interactive runs, e.g. in a script, are auto-confirmed).
2. **Every applied run writes an undo journal** to `~/.filetidy/history/`.
   `tidy undo --apply` walks the last run backwards, restoring names, locations
   and removing folders it created.
3. **Deletes are not deletes.** Duplicate removal moves files to
   `~/.filetidy/trash/<run-id>/`, so undo can bring them back. `--hard-delete`
   really unlinks and is the one operation undo cannot reverse.

Name collisions never silently overwrite: the default `--on-conflict number`
appends ` (1)`, ` (2)`. `--on-conflict skip` leaves the file alone, and
`--on-conflict overwrite` moves the displaced file to trash first.

## Commands

### `tidy sort DIRECTORY`

Move files into subfolders.

| Flag | Meaning |
| --- | --- |
| `--by type` | Documents, Images, Video, Audio, Archives, Code, ... (`tidy info` lists them) |
| `--by date` | date folders, format from `--date-format` (default `%Y-%m`) |
| `--by ext` | one folder per extension |
| `--by rules` | your rules file, see below |
| `--by type,date` | nest them: `Documents/2026-08/report.pdf` |
| `--dest DIR` | sort into another folder instead of in place |
| `--date-source` | `modified` (default) or `created` |
| `--rename PATTERN` | rename files as they are sorted |

```bash
tidy sort ~/Downloads --by type --apply
tidy sort ~/Downloads --by type,date --date-format '%Y/%m-%B' --apply
tidy sort ./project -r --by ext --dest ~/Sorted --apply
```

### `tidy rename DIRECTORY`

Rename in place, either from a pattern or a find/replace.

```bash
# ProjectName_2026-08-001.pdf, ProjectName_2026-08-002.pdf, ...
tidy rename ./scans --pattern '{project}_{date:%Y-%m}-{n:03}' --project ProjectName --apply

# strip a prefix from every name
tidy rename ./exports --replace 'Draft - ' --with '' --apply

# regex, and tidy up the result
tidy rename ./exports --replace '^\d+_' --with '' --regex --slug --apply
```

Tokens (usable in `--pattern`, in rule `target`s and rule `rename`s):

| Token | Value |
| --- | --- |
| `{name}` | original name without the extension |
| `{ext}` | extension without the dot |
| `{parent}` | containing folder name |
| `{project}` | `--project`, or the folder name |
| `{category}` | Documents / Images / ... |
| `{n}` | running counter - `{n:03}` gives `001` |
| `{size}` / `{sizeh}` | bytes / `1.4 MB` |
| `{hash}` | first 8 chars of the content hash |
| `{date}` `{modified}` `{created}` `{now}` | dates; `{date:%Y-%m}` takes any strftime spec, default `%Y-%m-%d` |

The extension is appended automatically unless the pattern already ends with it
(`--no-auto-ext` turns that off). Counter order comes from `--sort-by`
(`name`, `path`, `date`, `created`, `size`, `ext`) with `--reverse`, `--start`,
`--step`, and `--counter-scope dir|global`. Results are always sanitized: path
separators and characters illegal on Windows are replaced, so a pattern can
never write outside the target folder.

### `tidy dedupe DIRECTORY`

Finds byte-identical files regardless of name. Cheap checks run first - group by
size, then a 64 KB fingerprint, then a full hash - so unique files are never
fully read.

```bash
tidy dedupe ~/Downloads                                   # report only
tidy dedupe ~/Downloads --action move --keep oldest --apply
tidy dedupe ~/Downloads --action delete --keep shortest-name --apply
```

`--keep` picks the survivor: `oldest`, `newest`, `shortest-name`,
`longest-name`, `shallowest`, `first`. `--action move` puts the extra copies in
`<directory>/_duplicates` (override with `--quarantine`), preserving their
relative layout; that folder is excluded from later scans. Zero-byte files are
ignored unless you pass `--include-empty`.

### `tidy undo` / `tidy history` / `tidy info`

```bash
tidy history          # what has been run
tidy undo             # preview the reversal of the last run
tidy undo --apply     # actually reverse it
tidy undo --index 2 --apply   # reverse the run before that
tidy info             # tokens, categories, keep policies
```

Undo skips a file whose original path is occupied again, and reports it rather
than overwriting.

## File selection (all commands)

`-r/--recursive`, `--max-depth N`, `--include GLOB`, `--exclude GLOB` (both
repeatable), `--ext pdf --ext jpg`, `--min-size 10MB`, `--max-size 2GB`,
`--newer-than 7d`, `--older-than 2026-01-01`, `--hidden`, `--follow-symlinks`.

Hidden files, symlinks, `.git`/`node_modules`/`__pycache__`/`.venv`, and OS junk
like `.DS_Store` are skipped by default.

## Custom rules

A rules file is YAML or JSON. The first matching rule wins; files no rule claims
are left alone unless you set `default_target`. See
[`filetidy/rules.example.yaml`](../filetidy/rules.example.yaml).

```yaml
rules:
  - name: Invoices
    match:
      name: ["*invoice*", "*receipt*"]   # glob(s), case-insensitive
      ext: [pdf, png]                    # extensions
      regex: "^INV-[0-9]+"               # regex on the filename
      path: "src/**"                     # glob on the path relative to the root
      category: [Documents]              # a built-in category
      min_size: 10KB
      max_size: 20MB
      older_than: 30d                    # modified before now-30d
      newer_than: 2026-01-01
    target: "Finance/Invoices/{date:%Y}"
    rename: "Invoice_{date:%Y-%m-%d}_{n:03}.{ext}"   # optional

default_target: "Unsorted/{category}"
```

```bash
tidy sort ~/Downloads --by rules --rules rules.yaml --apply
```

Every key inside `match` is optional; a rule with several keys requires all of
them to match. Unknown keys are rejected with an error rather than silently
ignored.

## Recipes

```bash
# Weekly Downloads cleanup: quarantine duplicates, then sort what is left
tidy dedupe ~/Downloads --action move --keep oldest --apply -y
tidy sort   ~/Downloads --by type,date --apply -y

# Archive everything older than 90 days, keeping year folders
tidy sort ~/Downloads --older-than 90d --by date --date-format '%Y' \
          --dest ~/Archive --apply

# Number a folder of scans in capture order
tidy rename ./scans --sort-by created \
            --pattern '{project}_{date:%Y-%m}-{n:03}' --project Roadmap --apply

# Big stale installers only
tidy sort ~/Downloads --ext exe --ext dmg --min-size 50MB --older-than 30d \
          --by date --apply
```

## Install and run

Both forms run from the repo root, with no install step:

```bash
python tidy.py --help
python -m filetidy --help
```

`tidy.py` also works by absolute path from any directory
(`python /path/to/repo/tidy.py sort ~/Downloads`). To get a bare `tidy`
command, add an alias:

```bash
alias tidy='python3 /path/to/repo/tidy.py'
```

## Tests

```bash
python -m unittest discover -s tests
```
