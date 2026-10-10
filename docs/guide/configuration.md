# Configuration

## cass.toml

Lives in your course directory. `cass init` writes it; edit by hand freely.

```toml
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335
time_zone = "America/Los_Angeles"   # written by `cass init`; times you type are in this zone

[[canvas.quizzes]]
file = "quizzes/09-25-participation.toml"   # relative to this file
```

`[[canvas.modules]]`, `[[canvas.assignments]]`, and `[[canvas.quizzes]]` tables declare course content. `cass canvas sync` previews what differs from Canvas; `cass canvas sync --apply` creates what is missing and updates settings that differ. See [Module items](#module-items) for item declarations and [Quizzes](quizzes.md) for the quiz file format.

## Module items

A `[[canvas.modules]]` table with `[[canvas.modules.items]]` entries also controls what the module contains. `sync` reconciles those items. A module without `items` is never touched.

```toml
[[canvas.modules]]
name = "Week 1"
published = true

[[canvas.modules.items]]
type = "SubHeader"
title = "Readings"

[[canvas.modules.items]]
type = "File"
file = "readings/week1/intro.pdf"      # path below the course files root
source = "materials/intro.pdf"         # local file, relative to this file
published = true                       # unlocked for students
indent = 1

[[canvas.modules.items]]
type = "Page"
title = "Welcome"

[[canvas.modules.items]]
type = "Assignment"
title = "Reading response 1"

[[canvas.modules.items]]
type = "ExternalUrl"
title = "Course site"
url = "https://example.com/course"
```

`type` is one of `Assignment`, `Quiz`, `Page`, `File`, `ExternalUrl`, `SubHeader` (case-insensitive). `indent` (default 0) and `published` are allowed on every type. Unknown keys are errors.

| Type | Required | Optional |
|---|---|---|
| `Assignment`, `Quiz`, `Page` | `title`: the content's title | |
| `File` | `file`: path below the course files root | `title`, `source` |
| `ExternalUrl` | `url`, `title` | |
| `SubHeader` | `title` | |

Titles match case-insensitively. Assignment, Quiz and Page items show the content's own title. You can reference assignments and quizzes declared in the same file or created by the same `sync`. Only plain assignments match, not quiz or discussion assignments. `file` paths start below the root: `readings/w1.pdf`, not `course files/readings/w1.pdf`.

### Matching and outcomes

A declared item matches a live item by what it points at: the content ID, the page, the URL, or the file. SubHeaders have no content, so they pair by order. Duplicates pair in order too.

Each item gets one outcome in the `sync` table:

| Outcome | Meaning |
|---|---|
| `create` | No live item matches; one is added. |
| `update` | The item matches, but its title, indent or published state differs. |
| `move` | The item matches and only its position differs. |
| `keep` | Nothing to change. Shown as one count per module. |
| `extra` | A live item that is not declared. Left alone, and placed after the declared items. |
| `remove` | An undeclared item that `--prune` deletes. The linked content is untouched. |
| `upload` | A `File` source is uploaded (see below). Listed before the item's own row. |

The target order is the declared items in file order, then any extras in their current order. If the order differs, `--apply` sets the position of every item, so gaps in Canvas's numbering do not matter.

If an item cannot be found or is ambiguous, `sync` lists every such item across all modules and writes no module items. Under `--apply`, `sync` has already written modules, assignments and quizzes by then, and the error says so.

### Files

A `File` item with a `source` uploads the local file when the path does not exist on Canvas or the size differs. `sync` does not detect a same-size edit. Replace the file with `cass canvas files upload --on-duplicate overwrite`. An upload over an existing file replaces it in place, so the file ID and the item's link stay the same. Without `source`, the file must already exist.

For a `File`, `published` sets the file's lock, not the item's. `true` unlocks the file, `false` locks it. A new upload is locked unless `published = true`. An overwrite with `published` omitted keeps the file's current lock.

### Canvas quirks

- Canvas answers any `published` value with `403 item can't be unpublished`, even an unchanged one. cass sends `published` only when it changes.
- Items are read per module. `include[]=items` on the module list truncates long modules.
- `--prune` and `extra` only apply to modules that declare `items`. `items = []` declares an empty module.

## Times

cass reads times on the command line and in config files (`--due`, `--start`, `due_at`, quiz `unlock_at` / `due_at` / `lock_at`) in the course time zone unless they carry an explicit offset. `YYYY-MM-DD` means midnight; `YYYY-MM-DD HH:MM` is the usual form.

## Choosing a config

By default cass searches upward from the working directory for `cass.toml`. Point at another course with `--config PATH` or the `CASS_CONFIG` environment variable. The project root becomes that file's directory, so credentials and `cass.db` resolve beside it.

Python scripts follow the same rules: `CanvasClient()` honors `CASS_CONFIG`. To work with another course without changing the working directory or environment, build the client from its file:

```python
from cass.apis.canvas.client import CanvasClient

with CanvasClient.from_config("../f25/cass.toml") as c:
    print(c.get_course().name)
```

`from_config` reads the base URL, course ID and time zone from that file and the credentials from its directory, and leaves the project config alone.

## Credential files

| File | Contents | Created by |
|---|---|---|
| `.canvastoken` | Canvas API token | `cass init` |
| `.canvascreds` | `canvas_session` and `_csrf_token` cookies | `cass canvas login`, or by hand |

`.canvastoken` takes priority when both exist; `$CANVAS_TOKEN` is used when neither does. cass creates both with owner-only permissions and adds them to `.gitignore`; keep them out of version control.

## Local files

| File | Purpose |
|---|---|
| `cass.db` | SQLite database with all pulled data and pending edits |
| `backups/` | Snapshots from `cass backup` |
