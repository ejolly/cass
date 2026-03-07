# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas) and [GitHub Classroom](https://classroom.github.com/) — pull rosters, track submissions, edit grades, push back to Canvas.

All data lives in a local [DuckDB](https://duckdb.org/) database (`cass.duckdb`) alongside a version-trackable `cass.toml` config.

## Install

```bash
uv tool install cass
```

Requires [`uv`](https://docs.astral.sh/uv/). Also requires the [GitHub CLI](https://cli.github.com/) (`gh`) if using GitHub Classroom.

## Get started

Two paths to the same place — choose whichever fits your workflow.

### Browser (recommended)

```bash
cass view
```

If no config exists, the viewer walks you through setup: Canvas URL, course ID, API token, and optionally GitHub Classroom. It writes `cass.toml`, pulls your data, and opens the viewer — all in-browser.

### CLI

```bash
cass init        # interactive config setup
cass pull        # fetch students, assignments, submissions, grades
cass gradebook   # view the gradebook
```

Running `cass` with no arguments shows project status.

## Configuration

`cass.toml` lives in your project root. Canvas is required; GitHub Classroom is optional.

```toml
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335

# Optional — enables submission tracking and roster matching
[classroom]
id = 299058
org = "psyc-201"
```

Canvas API token goes in `canvas-token.txt` (same directory) or the `CANVAS_TOKEN` env var. Generate one in Canvas under Account > Settings > Approved Integrations.

### Declarative sync (optional)

Declare modules and assignments in `cass.toml`, then sync to Canvas:

```toml
[[canvas.modules]]
name = "Week 1"
published = true

[[canvas.assignments]]
name = "HW1"
points = 10
submission_types = ["online_url"]
due_at = "2026-01-20T23:59:59-08:00"
group = "Homework"
```

```bash
cass canvas sync --dry-run   # preview
cass canvas sync --apply     # push to Canvas
```

## Browser viewer

`cass view` opens a NiceGUI-powered UI for browsing, editing, and pushing data.

- **Navigate** tables by source group (Combined / Canvas / GitHub) in the sidebar
- **Edit** grades and assignment metadata by double-clicking cells
- **Push to Canvas** with a diff preview against live state and conflict warnings
- **Search** across rows with Ctrl/Cmd+K
- **Export** any table to CSV or Markdown

Editable tables show an "editable" badge. Changes are tracked as pending until you push or revert.

## CLI commands

### Data pipeline

```bash
cass pull                  # fetch everything
cass pull --students       # pull one stage only
cass pull --grades         # recompute grades from submissions
```

### View data

```bash
cass students              # roster
cass assignments           # assignment metadata
cass submissions hw-01     # submissions (optionally filtered by slug)
cass gradebook             # student x assignment matrix
```

All accept `--csv <file>`, `--save <file.md>`, and `--where "SQL expr"`.

### Grade sync

```bash
cass gradebook push           # dry-run preview
cass gradebook push --post    # push to Canvas
cass egrades                  # export eGrades CSV (UCSD format)
```

### Canvas management

```bash
cass canvas                # course overview
cass canvas people         # enrolled students
cass canvas modules        # list / create / publish modules
cass canvas assignments    # list / create assignments
cass canvas upload file.pdf
cass canvas announce "Title" "Body"
```

Run any subcommand with `--help` for full options.

### Database

```bash
cass query "SELECT * FROM students"   # one-off SQL
cass query                            # interactive DuckDB REPL
cass export students --csv roster.csv
cass import grades.csv                # auto-detects target table
```

### Backup & restore

```bash
cass backup                    # timestamped snapshot → backups/
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.duckdb
```

### Global flags

| Flag | Effect |
|------|--------|
| `--no-cache` | Bypass API cache |
| `--ttl N` | Cache TTL in hours (default: 6) |
| `-V` | Show version |

## How it works

```
cass.toml          →  config (git-tracked)
canvas-token.txt   →  credentials (gitignored)
cass.duckdb        →  all data (git-tracked, shareable)
.cass_cache.duckdb →  API cache (gitignored)
```

`cass pull` fetches from Canvas (and optionally GitHub), stores raw data in source tables (`canvas_students`, `gh_submissions`, etc.), then merges into unified master tables (`students`, `assignments`). Grades are computed from submissions and stored in `canvas_grades` for pushing back.

When both systems are configured, Canvas is the authoritative roster. GitHub students are auto-matched to Canvas students by name, with interactive CLI resolution for ambiguous cases.

## Collaborative workflow

Commit `cass.duckdb` to git for shared grading:

```bash
# TA grades, commits
cass pull --grades
git add cass.duckdb && git commit -m "grade hw-02" && git push

# Instructor reviews, pushes to Canvas
git pull
cass gradebook push --post
```

## Development

```bash
uv sync                    # install deps
uv run poe lint            # ruff format + check, ty, basedpyright
uv run poe test            # pytest
uv run poe install         # install as global CLI tool
```

## License

MIT
