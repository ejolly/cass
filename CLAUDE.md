# CLAUDE.md — cass (Classroom Assignment Grading CLI)

## Overview

`cass` is a CLI tool for grading classroom assignments. It supports **GitHub Classroom**, **Canvas LMS**, or **both** — configure whichever systems your course uses. Data is stored in a per-project DuckDB database (`cass.db`). No external database setup needed — everything is self-contained.

Installable via `uv tool install cass` or `uvx cass`.

---

## Setup

```bash
uv sync          # install deps (typer, rich, duckdb, msgspec, httpx + ruff/ty dev)
gh auth status   # verify GitHub CLI is authenticated (if using GitHub Classroom)
```

Requires: `uv`. Also `gh` (authenticated) if using GitHub Classroom.

---

## Configuration

`cass.toml` — discovered by walking up from cwd. At least one section required:

```toml
# GitHub Classroom only
[classroom]
id = 299058
org = "psyc-201"

# Canvas only
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335

# Both sections = combined mode (GH + Canvas matching, grade sync)
```

---

## CLI Usage

```bash
cass                                      # project status dashboard (default)
cass init                                 # scaffold config / check setup interactively
cass pull                                 # fetch everything from APIs → DuckDB
cass pull --students                      # pull students only
cass pull --assignments                   # pull assignments only
cass pull --submissions                   # pull submissions only
cass pull --grades                        # compute grades from submissions
cass pull --fetch                         # also download student files
cass pull --limit 5                       # limit students processed
cass students                             # show student roster
cass students --all                       # include excluded students
cass assignments                          # show assignment metadata
cass assignments --where "source='canvas'" # filter with SQL WHERE
cass submissions                          # show all submissions
cass submissions hw-01                    # filter by assignment slug
cass grades                               # gradebook matrix (students × assignments)
cass grades push                          # dry-run grade sync to Canvas
cass grades push --post                   # actually push grades
cass fetch hw-01                          # download student files
cass fetch all --force                    # re-download existing
cass query "SELECT * FROM students"       # raw DuckDB SQL query
cass query                                # interactive DuckDB REPL
cass view                                 # open cass.db in Dataflare (GUI viewer)
cass db                                   # interactive DuckDB REPL (alias)
cass db clean                             # clear api_cache for git commits
cass export grades --csv grades.csv       # export table to CSV
cass export students --md roster.md       # export table to markdown
cass import grades.csv                    # import CSV into DB (auto-detects table)
cass import data.csv --table students     # import with explicit table target
```

### Common flags on view commands
- `--save <file.md>` — write output as markdown
- `--csv <file.csv>` — export as CSV
- `--where "expr"` — SQL WHERE clause filter

### Global flags
- `--no-cache` — force API refresh
- `--ttl N` — cache TTL in hours (default: 6)

---

## Architecture

Python package (`cass/`) with Typer CLI, DuckDB storage, msgspec models, and Rich tables:

| File | Purpose |
|------|---------|
| `cass/__init__.py` | Package version |
| `cass/models/` | msgspec.Struct types split into domain.py, github_api.py, canvas_api.py, grading.py |
| `cass/config.py` | Config discovery (finds `cass.toml`), `has_classroom`/`has_canvas` properties |
| `cass/cli.py` | Typer app (status, init, students, assignments, submissions, grades, fetch, query, db, export, import) |
| `cass/github_client.py` | Async httpx GitHub API client with caching and concurrency control |
| `cass/pull.py` | Pull orchestration: students, assignments, submissions, grades, fetch phases |
| `cass/db.py` | DuckDB database: schema, CRUD for all models, cache, raw query |
| `cass/gh.py` | Subprocess wrapper for `gh api` with inline cache |
| `cass/classroom.py` | GH Classroom API: typed response structs, assignments, submissions, student discovery |
| `cass/canvas.py` | Canvas LMS: httpx client, assignments, submissions, student matching, grade push |
| `cass/fetch.py` | Download student files from repos |
| `cass/report.py` | Rich tables, CSV, markdown output formatting |

---

## Database

Per-project DuckDB file (`cass.db`) in the project root. Auto-created on first use.

Schema version 5. Tables:
- `meta` — schema version tracking
- `api_cache` — API responses with TTL (ephemeral, cleared by `cass db clean`)
- `students` — roster (identifier, github_username, github_id, name, email, canvas_id, excluded)
- `assignments` — unified metadata (id, source, title, slug, canvas_id, deadline, points_possible, accepted, submissions_count, passing_count)
- `submissions` — unified GH+Canvas (student_id, assignment_id, source, submitted, late, lateness_seconds, repo_name, commits_after_deadline, commit_count, passing, gh_autograder_score, score, workflow_state)
- `grades` — computed grades (student_id, assignment_id, grade, numeric_score, source)

All tables are queryable via `cass query "SQL"`, the interactive REPL (`cass query`), or directly with the `duckdb` CLI:

```bash
duckdb cass.db -c "SQL"              # quick one-off query
duckdb -readonly cass.db -c "SQL"    # safe read-only access
duckdb cass.db -csv -c "SQL"         # export as CSV
duckdb cass.db -json -c "SQL"        # export as JSON
duckdb cass.db                       # interactive REPL
```

Prefer `duckdb` CLI over Python for quick inspection, ad-hoc queries, and data checks.

---

## Data Flow

1. `cass init` → creates `cass.toml`
2. `cass pull` → fetches APIs → populates DuckDB (students → assignments → submissions → grades)
3. `cass students/assignments/submissions/grades` → read from DB, display as Rich tables
4. `cass grades push` → sync grades to Canvas
5. `cass fetch` → download student files from GitHub repos
6. `cass query` → direct DuckDB access for custom analysis

---

## Collaborative Workflow

`cass.db` is the shared source of truth — commit it to git. The `api_cache` table is ephemeral (~2MB of API responses); clear it before committing to keep the file small.

```bash
# TA grades hw-02, pushes
git pull
cass pull --grades
cass db clean
git add cass.db && git commit -m "grade hw-02" && git push

# Instructor pulls, reviews, pushes to Canvas
git pull
cass grades
cass grades push --post

# Manual edit flow
cass export grades --csv grades.csv
# edit in Excel/Numbers
cass import grades.csv
cass db clean
git add cass.db && git commit -m "manual grade adjustments" && git push
```

At this scale (15 students, <20 assignments), concurrent edits are unlikely. If a binary conflict occurs, last pusher re-pulls and re-applies.

---

## Grading Logic

`compute_grade()` in `cass/models/grading.py`:

**GitHub submissions:**
- No repo → `0` (numeric: 0)
- Late → `0 (+Dd HH:MM)` (numeric: 0)
- On time, 0 commits after deadline → `1` (numeric: 1)
- On time, N commits after → `1+ (N)` (numeric: 1)

**Canvas submissions:**
- Not submitted → `-` (numeric: None)
- Submitted, no score → `?` (numeric: None)
- Scored → `X/Y` or `X` (numeric: score)

---

## Coding Style

### Module structure
Every `.py` file follows this order:
1. Module docstring (always present)
2. `from __future__ import annotations` (if needed)
3. `__docformat__ = "google"`
4. Stdlib imports → third-party imports → relative imports

### Docstrings
- **Google-style** with `Args:`, `Returns:`, `Raises:` sections
- All public functions and classes get docstrings
- Skip docstrings on trivial one-liners where the signature is self-documenting
- `msgspec.Struct` classes get a one-line class docstring describing their role

### Type annotations
- All function signatures have return types
- Use `X | None` union syntax, not `Optional[X]`
- Use `list[X]`, `dict[K, V]` lowercase generics, not `List`/`Dict`

### Naming
- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_CASE` for module-level constants
- `_prefixed` for private/internal functions
- API response types: `GH`-prefixed (GitHub) or `Canvas`-prefixed
- Domain types: unprefixed (`Student`, `Assignment`, `Submission`, `Grade`)

### Error handling
- `SystemExit` for user-facing config/setup errors (missing token, no config file)
- `RuntimeError` for API/logic failures (assignment not found, rate limit exceeded)
- `typer.Exit(code=1)` in the CLI layer for user-visible errors
- `typer.Abort()` for user-cancelled operations

### CLI patterns
- **Lazy imports** inside command functions to keep startup fast
- Typer sub-apps for grouped commands (`grades_app`, `db_app`)
- Rich markup for console output: `[bold]`, `[red]`, `[green]`, `[dim]`, `[yellow]`
- `--where` flags include inline examples in help text

### Data layer
- `msgspec.Struct` for all data models (zero-copy decode from JSON)
- DuckDB singleton connection via `db.get_db()`
- Cache pattern: DuckDB-backed with TTL (`cache_load`/`cache_save`)
- Async: `asyncio.gather()` for parallel work, `asyncio.Semaphore` for concurrency control

---

## Dev

Task runner: [poethepoet](https://poethepoet.naber.me/) (dev dependency).

```bash
uv run poe lint            # format (ruff) + lint (ruff) + type check (ty)
uv run poe test            # run pytest suite
uv run poe docs            # generate API docs to docs/api/
uv run poe docs-serve      # live-preview API docs
uv build                   # build wheel + sdist
uv publish                 # publish to PyPI
```

**Always run before finishing work:**
```bash
uv run poe lint && uv run poe test
```
Both must pass clean.

---

## Project Management (Linear)

Project: **cass** — [linear.app/ejolly/project/cass-bd5285c72a0c](https://linear.app/ejolly/project/cass-bd5285c72a0c)
Team: **Ejolly** (EJO). Issues are prefixed `EJO-NNN`.

### Active issues

| Issue | Title | Priority | Dependencies |
|-------|-------|----------|------------|
| EJO-319 | Refactor data models: human-readable, self-documenting API + domain types | Urgent | Done |
| EJO-320 | Data storage & collaboration: single .db as git-shared source of truth | Urgent | Done |
| EJO-321 | User-friendly CLI commands for common data operations | High | Blocked by 319, 320 |
| EJO-322 | Canvas API compliance: User-Agent, rate limiting, 429 retry | High | Done |
| EJO-323 | Documentation: README, CLI help, Google-style docstrings, pdoc | Medium | Done |
| EJO-324 | Recommend Dataflare as interactive DB viewer/editor + CLI launcher | Low | Done |

Execution order:
```
EJO-319 (models) ──→ EJO-320 (storage) ──→ EJO-321 (CLI commands)
                                        ──→ EJO-323 (docs)
EJO-322 (Canvas API) — anytime, independent
EJO-324 (Dataflare)  — anytime, independent (small standalone PR)
```

### Linear CLI essentials

```bash
# List project issues
linear list-issues --project "cass"

# View an issue
linear get-issue --id EJO-319

# Create an issue
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2 --description "..."

# Update an issue (use full UUID or identifier)
linear save-issue --id EJO-319 --state "In Progress"
linear save-issue --id EJO-319 --state "Done"

# Link issues
linear save-issue --id EJO-321 --blocked-by "EJO-320"
linear save-issue --id EJO-321 --related-to "EJO-319,EJO-320"

# For complex descriptions, use --raw with JSON (bypasses flag parsing)
linear save-issue --raw '{"title": "...", "team": "Ejolly", "project": "cass", "description": "..."}'
# Or write JSON to a temp file first for long descriptions:
# linear save-issue --raw "$(cat /tmp/issue.json)"

# Priority values: 1=Urgent, 2=High, 3=Medium, 4=Low
# States: Backlog, Todo, In Progress, Done, Canceled
```
