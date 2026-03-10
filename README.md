# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas) and [GitHub Classroom](https://classroom.github.com/) — pull rosters, track submissions, edit grades, and push them back to Canvas.

All data lives in a local SQLite database (`cass.db`) alongside a version-trackable `cass.toml` config.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [GitHub CLI](https://cli.github.com/) (`gh`) — required for install and for GitHub Classroom features

## Install

```bash
# Authenticate with GitHub (one-time)
gh auth login

# Install cass as a CLI tool
uv tool install git+ssh://git@github.com/ejolly/cass.git
```

To update to the latest version:

```bash
uv tool install git+ssh://git@github.com/ejolly/cass.git --reinstall
```

After install, `cass` is available globally.

## Get started

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

Canvas API token goes in `.canvastoken` (same directory) or the `CANVAS_TOKEN` env var. Generate one in Canvas under **Account > Settings > Approved Integrations**.

## Browser viewer

`cass view` opens a NiceGUI-powered UI for browsing, editing, and pushing data.

- **Navigate** Canvas and GitHub data views in the sidebar
- **Edit** Canvas grades and assignment metadata by double-clicking cells
- **Push to Canvas** with a diff preview and conflict warnings
- **Search** across rows with Ctrl/Cmd+K
- **Export** any table to CSV or Markdown

## CLI commands

### Data pipeline

```bash
cass pull                  # fetch everything
cass pull --students       # pull one stage only
```

### Querying

```bash
cass query students        # roster
cass query assignments     # assignment metadata
cass query submissions     # submissions dataset
cass query gradebook       # student x assignment matrix
cass query --sql "select count(*) from students"
```

`cass query` also accepts `--where`, `--order`, and `--limit`.

### Grade sync

```bash
cass push                  # preview + confirm pending Canvas changes
cass push --yes            # skip confirmation
cass revert                # discard pending local changes
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

### Backup & restore

```bash
cass backup                        # timestamped snapshot → backups/
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.db
```

## Collaborative workflow

Commit `cass.db` to git for shared grading:

```bash
# TA grades, commits
git add cass.db && git commit -m "grade hw-02" && git push

# Instructor reviews, pushes to Canvas
git pull
cass push --yes
```

## How it works

```
cass.toml          →  config (git-tracked)
.canvastoken       →  credentials (gitignored)
cass.db            →  all data (git-tracked, shareable)
.cass_cache.db     →  API cache (gitignored)
```

`cass pull` fetches from Canvas (and optionally GitHub), stores raw data in source tables, then merges into unified master tables. When both systems are configured, Canvas is the authoritative roster and GitHub students are auto-matched by name.

## Development

```bash
uv sync                    # install deps
uv run poe lint            # ruff format + check, ty
uv run poe test            # pytest
uv run poe install         # install as global CLI tool
```

## License

MIT
