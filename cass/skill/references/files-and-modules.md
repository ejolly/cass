# Files, folders and modules

## Files

```bash
cass canvas files list --json                         # a tree; each line has kind file or folder
cass canvas files list --folder readings              # folder ID or path, with subfolders
cass canvas files upload intro.pdf --folder readings/week1 --dry-run
cass canvas files upload intro.pdf --folder readings/week1 --on-duplicate skip
cass canvas files upload draft.pdf --name intro.pdf --folder readings/week1
cass canvas files mv intro.pdf readings/week2 --dry-run
cass canvas files rename intro.pdf intro-v2.pdf --on-duplicate rename
cass canvas files publish intro.pdf                   # unlock; unpublish locks
cass canvas files delete intro.pdf --dry-run
cass canvas files folders list
cass canvas files folders create readings/week3 --dry-run
cass canvas files folders delete readings/old --force --yes
```

- Paths are relative to the course files root. `upload --folder` and `mv` create missing folders.
- `upload` locks a new file so students can't see it; `--publish` makes it visible. An overwrite keeps the existing file's lock unless you pass `--publish` or `--unpublished`.
- `--on-duplicate` takes `overwrite`, the default, which replaces the file with a new one under a new ID while module items and links follow. `rename` keeps both. `skip` skips on the same name and size.
- `folders delete` refuses a non-empty folder unless you pass `--force`.

## Module items, one at a time

```bash
cass canvas modules show "Week 1" --json              # module with its items and item IDs
cass canvas modules items add "Week 1" --type Assignment --content-id 123 --indent 1 --dry-run
cass canvas modules items add "Week 1" --type File --content-id 456 --dry-run
cass canvas modules items add "Week 1" --type Page --page-url syllabus --dry-run
cass canvas modules items add "Week 1" --type ExternalUrl --url https://example.com --title "Site" --dry-run
cass canvas modules items add "Week 1" --type SubHeader --title "Readings" --dry-run
cass canvas modules items update "Week 1" "Reading 1" --title "Reading 1 (revised)" --dry-run
cass canvas modules items move "Week 1" "Reading 1" --position 1 --dry-run
cass canvas modules items remove "Week 1" "Reading 1" --dry-run    # the linked content stays
```

- Get `--content-id` from `cass canvas assignments list --json`, `cass canvas quizzes list --json` or `cass canvas files list --json`.
- `items update` takes `--publish` or `--unpublish`. A new `ExternalUrl` or `SubHeader` is unpublished until you publish it, but only do that if asked.

## Module items declared in cass.toml

For a whole week or a whole term, declare the items and let `sync` reconcile them:

```toml
[[canvas.modules]]
name = "Week 1"
published = true                # omit to leave the live module as it is

[[canvas.modules.items]]
type = "SubHeader"
title = "Readings"

[[canvas.modules.items]]
type = "File"
file = "readings/week1/intro.pdf"      # below the course files root
source = "materials/intro.pdf"         # local; uploaded when missing or the size differs
indent = 1

[[canvas.modules.items]]
type = "Assignment"
title = "Reading response 1"           # matches the assignment's title
```

```bash
cass canvas sync                  # dry run: a table of actions
cass canvas sync --apply
cass canvas sync --prune          # preview removing undeclared items
cass canvas sync --prune --apply
```

- Types are `Assignment`, `Quiz`, `Page`, `File`, `ExternalUrl` and `SubHeader`. Each takes `indent` and `published`, and unknown keys are errors.
- `Assignment`, `Quiz` and `Page` need `title`. `File` needs `file`. `ExternalUrl` needs `url` and `title`. `SubHeader` needs `title`.
- Items match by what they point at. SubHeaders and duplicates pair in order. The target order is the declared items, then any extras.
- `extra` items are left alone. `--prune` removes them, but the linked content stays. A module without an `items` key is never touched, and `items = []` declares an empty module.
- `[[canvas.assignments]]` takes `name`, `points`, `due_at`, `group`, `submission_types` and `published`. On an existing assignment, `sync` updates only points (a 0 is ignored), due date and `published`. Missing assignment groups stop it, dry runs included, unless you pass `--create-groups`.
- A `refuse` row is a change to a quiz cass won't make because of attempts (see `quizzes.md`). A `fail` row is an assignment create or update Canvas rejected or didn't keep; a dry run usually can't predict it. It may still be applied, wholly or in part (a create that timed out may exist), so check Canvas before retrying. The rest is sent, and `sync` exits 1 without `Sync complete.`
- `sync` compares every `[[canvas.assignments]]` entry before it sends an assignment, so an unreadable due date stops it before any assignment changes; groups and modules are already written by then. When an error stops `sync --apply`, it prints a row for everything sent before the error; module item steps are listed in the error instead. The change that failed may also have been applied, and a quiz may be partly created (a `fail` row), so check Canvas.
- If any item can't be found or is ambiguous, `sync` writes no module items at all. Under `--apply`, it has already written modules, assignments and quizzes by then.
- `sync` misses a same-size edit to a `source` file. Upload it with `cass canvas files upload --on-duplicate overwrite`.
- For a `File`, `published` sets the file's lock, not the item's. A new upload stays locked unless the item declares `published = true`.
