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

`[[canvas.modules]]`, `[[canvas.assignments]]`, and `[[canvas.quizzes]]` tables declare course content. `cass canvas sync` previews what differs from Canvas; `cass canvas sync --apply` creates what is missing and updates settings that differ. See [Quizzes](quizzes.md) for the quiz file format.

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

`from_config` reads the base URL, course ID, time zone and credentials from that file and its directory, and leaves the project config alone.

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
