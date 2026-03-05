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
| `cass/models.py` | msgspec.Struct types: Student, GHStudentInfo, Assignment, Submission, Grade + compute_grade() |
| `cass/config.py` | Config discovery (finds `cass.toml`), `has_classroom`/`has_canvas` properties |
| `cass/cli.py` | Typer app (status, init, students, assignments, submissions, grades, fetch, query) |
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

Schema version 3. Tables:
- `meta` — schema version tracking
- `api_cache` — API responses with TTL
- `students` — roster (identifier, github_username, github_id, name, canvas_id, excluded)
- `assignments` — unified metadata (id, source, title, slug, canvas_id, deadline, points_possible)
- `submissions` — unified GH+Canvas (student_id, assignment_id, source, submitted, late, lateness_seconds, repo_name, commits_after, score, workflow_state)
- `grades` — computed grades (student_id, assignment_id, grade, numeric, source)

All tables are queryable via `cass query "SQL"` or the interactive REPL (`cass query`).

---

## Data Flow

1. `cass init` → creates `cass.toml`
2. `cass pull` → fetches APIs → populates DuckDB (students → assignments → submissions → grades)
3. `cass students/assignments/submissions/grades` → read from DB, display as Rich tables
4. `cass grades push` → sync grades to Canvas
5. `cass fetch` → download student files from GitHub repos
6. `cass query` → direct DuckDB access for custom analysis

---

## Grading Logic

`compute_grade()` in `cass/models.py`:

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

## Dev

Task runner: [poethepoet](https://poethepoet.naber.me/) (dev dependency).

```bash
uv run poe lint            # format (ruff) + lint (ruff) + type check (ty)
uv run poe test            # run pytest suite
uv build                   # build wheel + sdist
uv publish                 # publish to PyPI
```

**Always run before finishing work:**
```bash
uv run poe lint && uv run poe test
```
Both must pass clean.
