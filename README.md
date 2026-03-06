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
cass gradebook
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

### Declarative sync (optional)

Declare Canvas modules and assignments in `cass.toml`:

```toml
[[canvas.modules]]
name = "Week 1"
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
cass gradebook                   # gradebook matrix (students x assignments)
```

All view commands support:
- `--save <file.md>` — write output as markdown
- `--csv <file.csv>` — export as CSV
- `--where "expr"` — SQL WHERE clause filter

### Grade sync

```bash
cass gradebook push              # dry-run: preview what would be pushed to Canvas
cass gradebook push --post       # actually push grades
cass egrades                  # export eGrades CSV (UCSD final grade format)
cass egrades -o custom.csv    # custom output path
```

Assignments with a manual posting policy (`post_manually`) are auto-posted after grade push.

### Export & import

```bash
cass export grades --csv grades.csv    # export table to CSV
cass export students --md roster.md    # export table to markdown
cass import grades.csv                 # import CSV into DB (auto-detects table)
cass import data.csv --table students  # import with explicit table target
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
cass canvas modules create "Week 3"
cass canvas modules publish 123
cass canvas assignments       # list assignments
cass canvas assignments groups
cass canvas assignments create "HW2" --points 10
cass canvas quizzes           # list quizzes
cass canvas files             # file tree
cass canvas upload ./file.pdf
cass canvas announcements     # list announcements
cass canvas announce "Title" "Body"
cass canvas tabs              # list navigation tabs
cass canvas sync --dry-run    # preview config-as-data sync
cass canvas sync --apply      # apply config-as-data sync
```

### Backup & restore

```bash
cass backup                               # timestamped copy → backups/
cass backup --tag "pre-regrade"           # add a descriptive tag
cass backup --list                        # list existing backups
cass restore backups/cass_2026-03-05.duckdb  # restore (with confirmation)
```

### Database tools

```bash
cass query "SELECT * FROM students WHERE github_username IS NOT NULL"
cass query                    # interactive DuckDB REPL
cass view                     # browser-based database viewer
cass view --port 8080         # use a fixed port
```

### Global flags

- `--no-cache` — bypass API cache
- `--ttl N` — cache TTL in hours (default: 6)
- `-V` / `--version` — show version

## Browser viewer

`cass view` opens a NiceGUI-powered browser UI for browsing and editing the database.

- **Browse**: sidebar navigation by table group (Combined / Canvas / GitHub), sortable columns, search (Ctrl+K)
- **Edit**: double-click cells to edit, changes tracked as pending until pushed
- **Push to Canvas**: preview diff against live Canvas state, bulk push with conflict warnings
- **Export**: CSV export from any table
- **Dark mode**: automatic, follows system preference

Tables are grouped by source with read-only/editable badges. Combined (master) tables are always read-only. JOINed columns (student names, assignment names) are display-only.

## How it works

All data lives in a local [DuckDB](https://duckdb.org/) database (`cass.duckdb`) — no external database setup needed.

```
cass init    → creates cass.toml
cass pull    → fetches APIs → populates DuckDB
cass gradebook  → reads from DB → renders Rich tables
cass view    → browse/edit in browser
cass query   → direct SQL access
```

### Combined mode

When both `[classroom]` and `[canvas]` are configured, `cass pull` will:

1. Fetch the Canvas roster (authoritative source of truth for students)
2. Discover GitHub Classroom students from accepted assignments
3. Auto-match GitHub <> Canvas students by name (with interactive resolution for ambiguous cases)
4. Store source data in separate tables (`gh_*`, `canvas_*`) and merge into unified master tables
5. `cass gradebook push` syncs pre-computed Canvas grades directly

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
| Not submitted | `-` | -- |
| Submitted, not graded | `?` | -- |
| Graded | `42/50` | 42 |

## Database schema

`cass.duckdb` contains these tables (schema v9). API cache lives in `.cass_cache.duckdb` (gitignored).

**Source tables** (raw data from each platform):

| Table | Primary key |
|-------|-------------|
| `gh_students` | `github_username` |
| `canvas_students` | `canvas_id` |
| `gh_assignments` | `slug` |
| `canvas_assignments` | `canvas_id` |
| `gh_submissions` | `(github_username, assignment_slug)` |
| `canvas_submissions` | `(canvas_user_id, canvas_assignment_id)` |

**Master tables** (unified):

| Table | Primary key |
|-------|-------------|
| `students` | `canvas_id`, `github_username` UNIQUE |
| `assignments` | `slug`, `gh_assignment_slug` UNIQUE, `canvas_assignment_id` UNIQUE |

**Grade tables**:

| Table | Primary key |
|-------|-------------|
| `gh_grades` | `(github_username, assignment_slug)` |
| `canvas_grades` | `(canvas_user_id, canvas_assignment_id)` |

All tables are queryable via `cass query "SQL"` or directly with the `duckdb` CLI.

## Collaborative workflow

`cass.duckdb` is the shared source of truth — commit it to git. The API cache (`.cass_cache.duckdb`) is gitignored.

```bash
# TA grades hw-02, pushes
git pull
cass pull --grades
git add cass.duckdb && git commit -m "grade hw-02" && git push

# Instructor pulls, reviews, pushes to Canvas
git pull
cass gradebook
cass gradebook push --post
```

For manual edits:

```bash
cass export grades --csv grades.csv
# Edit in Excel/Numbers
cass import grades.csv
git add cass.duckdb && git commit -m "manual grade adjustments" && git push
```

## Troubleshooting

**`gh auth` fails or `gh` not found**
Install the [GitHub CLI](https://cli.github.com/) and run `gh auth login`.

**Canvas token not found**
Create `canvas-token.txt` in the project root or set `CANVAS_TOKEN`. Generate a token in Canvas under Account > Settings > Approved Integrations.

**Students missing from roster**
GitHub Classroom only discovers students who have accepted at least one assignment. For Canvas-only mode, all enrolled students are pulled automatically.

**Name matching failures (combined mode)**
`cass pull --students` will prompt for interactive resolution when names don't match. Matched pairs are saved to the database.

**Stale data**
Use `--no-cache` or `--ttl 0` for immediate expiry. Run `cass db clean` to clear all cached API responses.

## Development

```bash
uv sync                       # install all dependencies
uv run poe lint               # format + lint + type check (ruff, ty, basedpyright)
uv run poe test               # run test suite
uv run poe install            # install as global CLI tool
uv run poe docs               # generate API docs to docs/api/
```

## License

MIT
