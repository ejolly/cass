# cass

CLI grading toolkit for [GitHub Classroom](https://classroom.github.com/) and [Canvas LMS](https://www.instructure.com/canvas) — track submissions, deadlines, and sync grades.

Configure whichever systems your course uses: GitHub Classroom only, Canvas only, or both for combined roster matching and grade sync.

## Install

```bash
# Install as a CLI tool
uv tool install cass

# Or run directly without installing
uvx cass
```

Requires [`uv`](https://docs.astral.sh/uv/). Also requires the [GitHub CLI](https://cli.github.com/) (`gh`) if using GitHub Classroom.

## Quick start

```bash
# 1. Scaffold config and check setup
cass init

# 2. Pull everything from APIs into the local database
cass pull

# 3. View your data
cass students
cass assignments
cass submissions hw-01
cass grades
```

Running `cass` with no arguments shows a project status dashboard.

## Configuration

Create a `cass.toml` in your project root (or let `cass init` guide you). At least one section is required:

```toml
# GitHub Classroom
[classroom]
id = 299058
org = "psyc-201"

# Canvas LMS
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335
```

For Canvas, provide your API token via a `canvas-token.txt` file in the project root or the `CANVAS_TOKEN` environment variable.

## Configuration (advanced)

Declare Canvas modules and assignments in `cass.toml` for declarative sync:

```toml
[[canvas.modules]]
name = "Week 1"
published = false

[[canvas.modules]]
name = "Week 2"
published = true

[[canvas.assignments]]
name = "HW1"
points = 10
submission_types = ["online_url"]
due_at = "2026-01-20T23:59:59-08:00"
published = true
group = "Homework"
```

Run `cass canvas sync --dry-run` to preview changes, then `cass canvas sync --apply` to push to Canvas.

## Commands

### Pull data

```bash
cass pull                     # fetch everything: students → assignments → submissions → grades
cass pull --students          # pull students only
cass pull --assignments       # pull assignments only
cass pull --submissions       # pull submissions only
cass pull --grades            # compute grades from submissions
cass pull --fetch             # also download student files
cass pull --limit 5           # limit students processed
```

### View data

```bash
cass students                 # student roster
cass students --all           # include excluded students
cass assignments              # assignment metadata
cass submissions              # all submissions
cass submissions hw-01        # filter by assignment slug
cass grades                   # gradebook matrix (students x assignments)
```

All view commands support:
- `--save <file.md>` — write output as markdown
- `--csv <file.csv>` — export as CSV
- `--where "expr"` — SQL WHERE clause filter

### Grade sync

```bash
cass grades push              # dry-run: preview what would be pushed to Canvas
cass grades push --post       # actually push grades
```

### File downloads

```bash
cass fetch hw-01              # download student files for an assignment
cass fetch all --force        # re-download everything
```

### Canvas management

```bash
cass canvas                   # course overview with resource counts
cass canvas people            # enrolled students
cass canvas modules           # list modules
cass canvas modules 123       # module detail with items
cass canvas modules create "Week 3"  # create a module
cass canvas modules publish 123      # publish a module
cass canvas modules add-item 123 --page "Welcome"  # add item to module
cass canvas assignments              # list assignments
cass canvas assignments 456          # assignment detail
cass canvas assignments groups       # assignment groups
cass canvas assignments create "HW2" --points 10
cass canvas quizzes                  # list quizzes
cass canvas files                    # file tree
cass canvas upload ./file.pdf        # upload a file
cass canvas announcements            # list announcements
cass canvas announce "Title" "Body"  # post announcement
cass canvas tabs                     # list navigation tabs
cass canvas sync --dry-run           # preview config-as-data sync
cass canvas sync --apply             # apply config-as-data sync
```

### Database tools

```bash
cass query "SELECT * FROM students WHERE canvas_id != ''"
cass query                    # interactive DuckDB REPL
cass view                     # open cass.db in Dataflare (GUI viewer)
```

[Dataflare](https://dataflare.app/) is a recommended GUI for browsing and editing the database interactively. Install with `brew install --cask dataflare`.

### Global flags

- `--no-cache` — bypass API cache
- `--ttl N` — cache TTL in hours (default: 6)
- `-V` / `--version` — show version

## How it works

All data lives in a local [DuckDB](https://duckdb.org/) database (`cass.db`) — no external database setup needed.

```
cass init    → creates cass.toml
cass pull    → fetches APIs → populates DuckDB
cass grades  → reads from DB → renders Rich tables
cass query   → direct SQL access for custom analysis
```

### Combined mode

When both `[classroom]` and `[canvas]` are configured, `cass pull` will:

1. Discover students from GitHub Classroom accepted assignments
2. Fetch the Canvas course roster
3. Auto-match GitHub ↔ Canvas students by name (with interactive resolution for ambiguous cases)
4. Store both GitHub and Canvas assignments/submissions in a unified schema
5. `cass grades push` maps GitHub assignment grades to their Canvas counterparts by name-token overlap

### Grading logic

**GitHub submissions** (binary: did you submit on time?)

| Condition | Grade | Numeric |
|-----------|-------|---------|
| No repo | `0` | 0 |
| Late | `0 (+1d 02:00)` | 0 |
| On time, no commits after deadline | `1` | 1 |
| On time, N commits after deadline | `1+ (N)` | 1 |

**Canvas submissions** (scored by the LMS)

| Condition | Grade | Numeric |
|-----------|-------|---------|
| Not submitted | `-` | — |
| Submitted, not graded | `?` | — |
| Graded | `42/50` | 42 |

## Architecture

| Module | Purpose |
|--------|---------|
| `cli.py` | Typer CLI — all commands, flags, and output |
| `cli_canvas.py` | `cass canvas` subcommands — browse and modify Canvas course content |
| `config.py` | Config discovery (`cass.toml`), prerequisite checks, config-as-data specs |
| `pull.py` | Orchestrates the students → assignments → submissions → grades pipeline |
| `classroom.py` | GitHub Classroom API — async with parallel per-student fetching |
| `canvas.py` | Canvas business logic — roster matching, name normalization, grade sync |
| `canvas_api.py` | Canvas HTTP client — typed `CanvasClient`, retry transport, token management |
| `github_client.py` | Async httpx GitHub API client with caching and concurrency control |
| `gh.py` | Subprocess wrapper for `gh api` (used by fetch.py) |
| `db.py` | DuckDB database — schema, CRUD, cache, raw queries |
| `fetch.py` | Download student files from GitHub repos |
| `report.py` | Output formatting — Rich tables, CSV, and markdown |
| `models/` | msgspec.Struct types split into domain, github_api, canvas_api, grading |

## Database schema

The `cass.db` file contains these tables (schema version 5):

| Table | Description | Key columns |
|-------|-------------|-------------|
| `students` | Course roster | `identifier`, `github_username`, `canvas_id`, `excluded` |
| `assignments` | Unified assignment metadata | `id` (PK), `source`, `title`, `deadline`, `points_possible` |
| `submissions` | Per-student submission data | `(student_id, assignment_id)` PK, `submitted`, `late`, `score` |
| `grades` | Computed/manual grades | `(student_id, assignment_id)` PK, `grade`, `numeric_score` |
| `api_cache` | Ephemeral API response cache | `endpoint` (PK), `data`, `fetched_at` |
| `meta` | Schema version tracking | `key`, `value` |

Example queries:

```sql
-- Students matched to Canvas
SELECT identifier, github_username, canvas_id FROM students WHERE canvas_id != '';

-- Late submissions
SELECT student_id, assignment_id, lateness_seconds FROM submissions WHERE late = true;

-- Average score per Canvas assignment
SELECT assignment_id, AVG(numeric_score) FROM grades WHERE source = 'auto' GROUP BY 1;
```

## Collaborative workflow

`cass.db` is the shared source of truth — commit it to git. Clear the `api_cache` table before committing to keep the file small.

```bash
# TA grades hw-02, pushes
git pull
cass pull --grades
cass db clean                 # clear api_cache (~2MB of API responses)
git add cass.db && git commit -m "grade hw-02" && git push

# Instructor pulls, reviews, pushes to Canvas
git pull
cass grades
cass grades push --post
```

For manual edits (adjustments, overrides):

```bash
cass export grades --csv grades.csv
# Edit in Excel/Numbers
cass import grades.csv
cass db clean
git add cass.db && git commit -m "manual grade adjustments" && git push
```

## Troubleshooting

**`gh auth` fails or `gh` not found**
Install the [GitHub CLI](https://cli.github.com/) and run `gh auth login`. Verify with `gh auth status`.

**Canvas token not found**
Create `canvas-token.txt` in the project root containing your API token, or set the `CANVAS_TOKEN` environment variable. Generate a token in Canvas under Account → Settings → Approved Integrations.

**Students missing from roster**
GitHub Classroom only discovers students who have accepted at least one assignment. Run `cass pull --students` after students accept. For Canvas-only mode, all enrolled students are pulled automatically.

**Name matching failures (combined mode)**
When GitHub and Canvas names don't match automatically, `cass pull --students` will prompt for interactive resolution. Matched pairs are saved to the database — you only need to resolve once.

**Stale data**
Use `--no-cache` to bypass the API cache, or `--ttl 0` for immediate expiry. Run `cass db clean` to clear all cached API responses.

## Development

```bash
uv sync                       # install all dependencies
uv run poe lint               # format + lint + type check
uv run poe test               # run test suite
uv run poe docs               # generate API docs to docs/api/
uv run poe docs-serve         # live-preview API docs
```

## License

MIT
