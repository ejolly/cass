# CLAUDE.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. DuckDB storage, Typer CLI, Elm browser viewer.

## Setup

```bash
uv sync          # install deps
gh auth status   # verify GH CLI auth (if using GitHub Classroom)
```

## Dev

```bash
uv run poe lint            # ruff format → ruff check → ty → basedpyright → biome → elm-format
uv run poe test            # pytest
uv run poe elm-build       # elm-format → elm make --optimize → copy to viewer/
uv run poe install         # uv tool install . --force
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
    ├── index.html           # Elm HTML shell + JS ports
    ├── index_classic.html   # legacy AG Grid viewer (--classic flag)
    ├── elm.js               # compiled Elm output (committed, rebuilt via poe elm-build)
    └── elm/
        ├── elm.json         # Elm 0.19.1 deps (elm-ui, elm-advanced-grid 1.0.1)
        └── src/
            ├── Main.elm     # TEA core: init, update, subscriptions, ports
            ├── Types.elm    # Model, Msg, all type aliases, ModalState
            ├── View.elm     # elm-ui rendering, grid config, keyboard shortcuts
            ├── Api.elm      # HTTP commands, JSON decoders, search, CSV export
            └── Theme.elm    # light/dark palettes, mono font stack
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

`cass view` opens an Elm-powered browser UI. `--classic` falls back to AG Grid.

**Python server** (`viewer/__init__.py`):
- stdlib HTTPServer with ViewerHandler
- `_READ_ONLY_TABLES`: canvas_submissions, gh_submissions, gh_grades
- `_CANVAS_PUSHABLE`: canvas_assignments (name, points_possible, due_at, published) + canvas_grades (posted_grade)
- `_ENRICHED_QUERIES`: JOIN student_name, assignment_name, assignment_group onto ID-heavy tables
- Pending changes tracked in-memory; preview compares against live Canvas before apply
- Bulk grade push per assignment + auto-post for post_manually assignments

**Elm frontend** (elm-ui + elm-advanced-grid 1.0.1):
- Data normalized to `Row = { values : Dict String String }` for uniform grid display
- JOINed columns are NOT editable (frontend checks `realCols` from schema)
- Cell editing: JS dblclick port → Elm edit bar → POST /api/update/{table}
- Canvas push: modal state machine (ModalClosed → ModalLoading → ModalPreview → ModalPushing → ModalResults)
- Dark mode via `prefers-color-scheme` media query → Elm Flags
- Keyboard: Ctrl/Cmd+K (search focus), Escape (close modal > cancel edit)
- elm-advanced-grid CSS requires `!important` overrides for theming

**elm-advanced-grid 1.0.1 API** (differs from unreleased v2):
- `init : Config a -> List a -> Model a` (returns Model, not tuple)
- `Config`: `containerHeight/Width` ints, `rowClass : Item a -> String`, `headerHeight`, no `footerHeight`/`labels`
- `Item a = { data : a, index : Int, selected : Bool }` — NOT exported; use inline lambdas
- `stringColumnConfig` takes 1 arg record: `{id, title, tooltip, width, getter, localize}` (no editor/setter)

**Elm build**: `poe elm-build` runs elm-format + elm make --optimize, copies elm.js to viewer/. The compiled elm.js is committed.

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

## Elm Coding Style

### Architecture (TEA)
- **One flat `Msg` type** in Types.elm. Only nest for third-party stateful components (e.g., `GridMsg (Grid.Msg Row)`). Do NOT nest to "organize" messages — use comment separators instead.
- **One big `update` function** in Main.elm. Extract helpers as named functions with type signatures when a branch exceeds ~10 lines, but keep them in Main — don't create mini-TEA modules for UI sections.
- **View functions are just functions**, not components. `viewSidebar`, `viewModal`, etc. live in View.elm with comment section headers (`-- SIDEBAR`, `-- MODAL`). No component lifecycle, no separate Model/update per UI section.
- **Ports in Main** (currently 2). Only move to a dedicated `Ports.elm` if count exceeds 5.
- **Types.elm breaks circular imports** between Main, View, and Api. Acceptable at current scale (~270 lines). Extract a type to its own module only when it accumulates multiple associated functions (e.g., `TableSource` + `classifyTable` + future helpers).

### Type design
- **Custom types over booleans/strings** for fixed sets of values: `StatusLevel`, `TableSource`, `ModalState`. The compiler enforces exhaustive matching — no silent typos.
- **Make impossible states impossible**: model correlated state as a single custom type with variants carrying only relevant data (see `ModalState`). Never use `Bool` + `Maybe` pairs for state that has more than 2 meaningful configurations.
- **Unwrap Maybe/Result early**: parent view functions should unwrap and pass concrete values to children. Sub-views should not receive `Maybe` values they must redundantly pattern-match.
- **Type annotations on every top-level function**. No exceptions.

### Module conventions
- **Explicit `exposing` lists** on module declarations (never `exposing (..)`). Documents the public API.
- **`import Types exposing (..)`** in Main.elm is the one accepted exception — Types is consumed by every module.
- All other imports use qualified access or selective `exposing` of specific names.
- **Module split heuristic**: don't split preemptively. 400–1000 lines is normal; push to comment-section-headers before splitting. Split only when code has distinct responsibilities that change independently.

### elm-ui patterns
- **`spacing` on parent, not children** — elm-ui has no margin concept. Spacing is always set on the container.
- **`paragraph` for wrapping text** — `el`, `row`, `column` do NOT wrap text. Only `paragraph` does.
- **`Region.*` for accessibility**: `Region.navigation` on sidebar, `Region.mainContent` on main area, `Region.heading N` for headings, `Region.announce` for status messages.
- **`layoutWith` + `focusStyle`** to reset default focus outline, then apply custom `focused` styles per element.
- **Palette as first argument** to view helpers: `viewFoo : Palette -> ... -> Element Msg`.
- **`Element.html`** only for leaf-node third-party widgets (e.g., Grid.view). Never for layout containers.
- **`htmlAttribute`** is an escape hatch — comment why each use is needed.

### Theme module (Theme.elm)
- Spacing scale on 4px base unit (`sp1 = 4`, `sp2 = 8`, ...) — never use bare integer literals for spacing/padding.
- Font sizes as named constants (`textXs`, `textSm`, `textBase`).
- Typed `Palette` record with light/dark variants — compiler enforces completeness when adding new colors.
- All color references go through the palette — no inline `rgb255` in view code.

### Decoders (Api.elm)
- Use `D.mapN` with constructor functions for combining fields. For 4+ fields, prefer pipeline style (consider `elm-json-decode-pipeline`).
- `D.oneOf` for fields with optional or varying types.
- `resolveJson` helper for `Http.task` resolver pattern.

### What NOT to do in the Elm viewer
- Do NOT create component modules with their own Model/update for UI sections (sidebar, modal, toolbar).
- Do NOT use opaque types for app-internal types at this scale — the single-consumer overhead is not worth it.
- Do NOT use `Element.Lazy` without benchmarking — the comparison overhead can exceed the rendering cost for simple elements.
- Do NOT use `_` wildcard matching in case expressions that should be exhaustive (defeats the compiler's safety guarantees).

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
| EJO-334 | Elm viewer: standardize around best practices | Medium | Backlog |

```bash
linear list-issues --project "cass"
linear get-issue --id EJO-321
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2 --description "..."
linear save-issue --id EJO-321 --state "In Progress"
# Priority: 1=Urgent, 2=High, 3=Medium, 4=Low
# States: Backlog, Todo, In Progress, Done, Canceled
```
