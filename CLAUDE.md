# CLAUDE.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. DuckDB storage, Typer CLI, Svelte browser viewer.

## Setup

```bash
uv sync          # install deps
gh auth status   # verify GH CLI auth (if using GitHub Classroom)
```

## Dev

```bash
uv run poe lint            # ruff format → ruff check → ty → basedpyright → biome → svelte-check
uv run poe test            # pytest
uv run poe ui-build        # build Svelte frontend
uv run poe install         # ui-build + uv tool install . --force
uv run poe docs            # pdoc → docs/api/
```

**Always run before finishing work:** `uv run poe lint && uv run poe test`

---

## Package Structure

```
cass/
├── __init__.py              # version
├── config.py                # cass.toml discovery, CanvasModuleSpec/AssignmentSpec
├── db.py                    # DuckDB schema v9, CRUD for all tables
├── cache.py                 # API cache in .cass_cache.duckdb (separate from main DB)
├── pull.py                  # orchestration: students → assignments → submissions → grades
├── models/
│   ├── __init__.py          # re-exports all types
│   ├── domain.py            # Student, Assignment, GHSubmission, CanvasSubmission, GHGrade, CanvasGrade
│   ├── github_api.py        # GH* response structs (GHAssignment, GHAcceptedAssignment, etc.)
│   ├── canvas_api.py        # Canvas* response structs (CanvasCourse, CanvasStudent, etc.)
│   └── grading.py           # compute_gh_grade(), compute_canvas_grade(), format_lateness()
├── cli/
│   ├── __init__.py          # Typer app + all commands (entry point: cass.cli:app)
│   ├── canvas.py            # cass canvas subcommands (modules, assignments, quizzes, files, sync)
│   └── report.py            # Rich tables, CSV, markdown output
├── github/
│   ├── client.py            # async httpx client (GitHubClient), semaphore concurrency
│   ├── gh.py                # subprocess wrapper for `gh api`
│   ├── classroom.py         # GH Classroom API: assignments, submissions, student discovery
│   └── fetch.py             # download student files from repos
├── canvas/
│   ├── client.py            # CanvasClient (typed httpx), _RetryTransport, GraphQL, bulk grade push
│   ├── matching.py          # roster matching, name normalization, slugify()
│   └── egrades.py           # UCSD eGrades CSV export
└── viewer/
    ├── __init__.py          # stdlib HTTP server, pending change tracking, Canvas sync
    ├── index_classic.html   # legacy AG Grid viewer (--classic flag)
    ├── dist/                # Svelte build output (committed, rebuilt via poe ui-build)
    └── ui/                  # Svelte 5 + shadcn-svelte + TanStack Table source
```

---

## Database (Schema v9)

DuckDB file `cass.duckdb` (committed to git). Cache in `.cass_cache.duckdb` (gitignored).

**Source tables** (raw platform data):
- `gh_students` (PK: github_username), `canvas_students` (PK: canvas_id)
- `gh_assignments` (PK: slug), `canvas_assignments` (PK: canvas_id, has post_manually flag)
- `gh_submissions` (PK: github_username + assignment_slug), `canvas_submissions` (PK: canvas_user_id + canvas_assignment_id)

**Master tables** (unified):
- `students` (PK: canvas_id, UNIQUE: github_username)
- `assignments` (PK: slug, UNIQUE: gh_assignment_slug, UNIQUE: canvas_assignment_id)

**Grade tables**:
- `gh_grades` (PK: github_username + assignment_slug)
- `canvas_grades` (PK: canvas_user_id + canvas_assignment_id) — this is the push target

DuckDB `INSERT OR REPLACE` fails with multiple UNIQUE constraints — use `INSERT ... ON CONFLICT (pk) DO UPDATE SET ...`.

CLI commands query source tables with inline JOINs (no views — removed in v6 as confusing).

---

## Viewer Architecture

`cass view` opens a Svelte-powered browser UI. `--classic` falls back to AG Grid.

**Python server** (`viewer/__init__.py`):
- stdlib HTTPServer with ViewerHandler
- `_READ_ONLY_TABLES`: canvas_submissions, gh_submissions, gh_grades
- `_CANVAS_PUSHABLE`: canvas_assignments (name, points_possible, due_at, published) + canvas_grades (posted_grade)
- `_ENRICHED_QUERIES`: JOIN student_name, assignment_name, assignment_group onto ID-heavy tables
- Pending changes tracked in-memory; preview compares against live Canvas before apply
- Bulk grade push per assignment + auto-post for post_manually assignments

**Svelte frontend** (`viewer/ui/` → built to `viewer/dist/`):
- Svelte 5 + shadcn-svelte + TanStack Table
- Built with `poe ui-build`, output committed to `viewer/dist/`

---

## Canvas Integration

**CanvasClient** (`canvas/client.py`):
- Typed httpx client, all methods return msgspec.Struct instances
- `_RetryTransport`: 429 retry with exponential backoff, proactive throttle on low X-Rate-Limit-Remaining
- Token from `canvas-token.txt` or `$CANVAS_TOKEN`
- GraphQL via `_graphql()` for `postAssignmentGrades` / `hideAssignmentGrades` mutations
- Bulk grade push: `POST /submissions/update_grades` returns CanvasProgress (poll until complete)
- Assignment IDs are strings in GraphQL variables

**canvas/matching.py**: business logic only (matching, slugify). Delegates API calls to CanvasClient.

**canvas_api.py gotchas**:
- `CanvasSubmissionResponse` (API type) vs `CanvasSubmission` (domain type) — different structs
- `CanvasFile.content_type` uses `msgspec.field(name="content-type")` (hyphenated API field)
- Canvas tab IDs are strings, not ints

---

## Python Coding Style

### Module structure
1. Module docstring (always present)
2. `from __future__ import annotations` (if needed)
3. `__docformat__ = "google"`
4. Stdlib → third-party → relative imports

### Python conventions
- Google-style docstrings (`Args:`, `Returns:`, `Raises:`) on all public functions
- `msgspec.Struct` for all data models; one-line class docstring
- All function signatures have return types; `X | None` not `Optional[X]`; lowercase generics
- `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants, `_prefixed` private
- API types: `GH`-prefixed (GitHub), `Canvas`-prefixed. Domain types: unprefixed
- Lazy imports inside CLI command functions (fast startup)
- `TYPE_CHECKING` guard for type-only imports in CLI modules
- `# pyright: ignore[ruleCode]` for suppression (NOT `# type: ignore`)

### Error handling
- `SystemExit` for config/setup errors
- `RuntimeError` for API/logic failures
- `typer.Exit(code=1)` in CLI layer
- `typer.Abort()` for user cancellation

### Data layer
- DuckDB singleton via `db.get_db()`
- Cache: DuckDB-backed TTL in separate file (`cache_load`/`cache_save`)
- Async: `asyncio.gather()` for parallel, `asyncio.Semaphore` for concurrency (MAX_CONCURRENCY=10)

---

## Testing

161 tests across 9 files. Key patterns:
- `db_conn` fixture: in-memory DuckDB, monkeypatched as module singleton
- `project_dir` fixture: tmp_path with minimal cass.toml
- CanvasClient tests use `_MockTransport` (pre-configured response queue)
- Parametrized edge cases for grading boundaries, name normalization, struct decoding
- Viewer tests: HTTPServer on random port with urllib client

---

## Type Checking

basedpyright strict mode — zero errors across all Python source.
- 4 legitimate `# pyright: ignore` at dynamic boundaries (JSON parsing, list.extend)
- Viewer uses type aliases: `_ChangeFields`, `_RowChanges`, `_TableChanges`, `_PendingChanges`

---

## Project Management (Linear)

Project: **cass** — Team: **Ejolly** (EJO)

| Issue | Title | Priority | Status |
|-------|-------|----------|--------|
| EJO-321 | User-friendly CLI commands for common data operations | High | Backlog |
| EJO-334 | Svelte viewer: standardize around best practices | Medium | Backlog |

```bash
linear list-issues --project "cass"
linear get-issue --id EJO-321
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2 --description "..."
linear save-issue --id EJO-321 --state "In Progress"
# Priority: 1=Urgent, 2=High, 3=Medium, 4=Low
# States: Backlog, Todo, In Progress, Done, Canceled
```
