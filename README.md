# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas) and [GitHub Classroom](https://classroom.github.com/) — pull rosters, track submissions, manually edit Canvas grades, and push them back to Canvas.

All app data lives in a local SQLite database (`cass.db`) alongside a version-trackable `cass.toml` config. The checked-in `cass.duckdb` is used only as a local integration-test fixture source.

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
cass init         # interactive config setup
cass pull         # fetch students, assignments, submissions
cass status       # overview of local state and sync status
```

Running `cass` with no arguments shows help.

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

Canvas API token goes in `.canvastoken` (same directory) or the `CANVAS_TOKEN` env var. Generate one in Canvas under Account > Settings > Approved Integrations.

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

This project configuration is generated and managed through the CLI/setup flows and identifies the current project directory with a specific Canvas course and optional GitHub Classroom.

## Browser viewer

`cass view` opens a NiceGUI-powered UI for browsing, editing, and pushing data.

- **Navigate** Canvas and GitHub data views in the sidebar
- **Edit** Canvas grades and assignment metadata by double-clicking cells
- **Push to Canvas** with a diff preview against live state and conflict warnings
- **Search** across rows with Ctrl/Cmd+K
- **Export** any table to CSV or Markdown

Editable tables show an "editable" badge. Changes are tracked as pending until you push or revert.

## CLI commands

### Data pipeline

```bash
cass pull                  # fetch everything
cass pull --students       # pull one stage only
```

### Workflow

```bash
cass status                # local DB + sync overview
cass query students        # roster
cass query assignments     # assignment metadata
cass query submissions     # submissions dataset
cass query gradebook       # student x assignment matrix
```

`cass query` also accepts `--where`, `--order`, and `--limit`.

### Grade sync

```bash
cass push                  # preview + confirm pending Canvas changes
cass push --yes            # skip confirmation prompt
cass revert                # discard pending local changes
cass egrades               # export eGrades CSV (UCSD format)
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

### Querying

```bash
cass query students
cass query assignments --limit 20
cass query --sql "select count(*) from students"
```

### Backup & restore

```bash
cass backup                    # timestamped snapshot → backups/
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.db
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
.canvastoken      →  credentials (gitignored)
cass.db            →  all data (git-tracked, shareable)
.cass_cache.db     →  API cache (gitignored)
```

`cass pull` fetches from Canvas (and optionally GitHub), stores raw data in source tables (`canvas_students`, `gh_submissions`, etc.), then merges into unified master tables (`students`, `assignments`). `canvas_grades` remains a manual working table for review and Canvas push.

When both systems are configured, Canvas is the authoritative roster. GitHub students are auto-matched to Canvas students by name, with interactive CLI resolution for ambiguous cases.

## Collaborative workflow

Commit `cass.db` to git for shared grading:

```bash
# TA grades, commits
git add cass.db && git commit -m "grade hw-02" && git push

# Instructor reviews, pushes to Canvas
git pull
cass push --yes
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
