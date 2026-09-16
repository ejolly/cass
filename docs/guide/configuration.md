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

## Credential files

| File | Contents | Created by |
|---|---|---|
| `.canvastoken` | Canvas API token | `cass init` |
| `.canvascreds` | `canvas_session` and `_csrf_token` cookies | `cass canvas login`, or by hand |

`.canvascreds` takes priority when both exist. cass creates both with owner-only permissions and adds them to `.gitignore`; keep them out of version control.

## Local files

| File | Purpose |
|---|---|
| `cass.db` | SQLite database with all pulled data and pending edits |
| `backups/` | Snapshots from `cass backup` |
