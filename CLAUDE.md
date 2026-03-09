# CLAUDE.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. SQLite storage, Typer CLI, NiceGUI browser viewer.

## Architecture

CLI (`cass/cli/`) and viewer (`cass/viewer/`) are thin interfaces over a shared functional core.
**Never** put business logic, data transforms, queries, or API calls in CLI or viewer code.
Always use existing models (`db/schema.py`, `apis/*/schema.py`), operations (`db/`, `apis/`, `actions/`), and catalog metadata (`db/catalog.py`). No ad-hoc dicts, raw SQL in interfaces, or one-off data wrangling — if it doesn't exist in core, add it there first.

```
CLI / Viewer  →  actions/  →  db/     →  SQLite
                  apis/       catalog
```

## Commands

```bash
uv sync                    # install deps
uv run poe lint            # ruff format → ruff check → ty → basedpyright
uv run poe test            # pytest
uv run poe install         # uv tool install . --force
```

**Always run `uv run poe lint && uv run poe test` before finishing work.**

Use `symbex` for token-efficient code exploration:

```bash
symbex -s -d cass/             # all signatures
symbex '*Client*' -s -d cass/  # find classes/functions matching pattern
```

## Style

- File header: `from __future__ import annotations` → `__docformat__ = "google"` → imports
- `msgspec.Struct` for API response types; `dataclass` for internal service types
- API types: `GH`/`Canvas`-prefixed. Domain types: unprefixed
- Error handling: `SystemExit` (config), `RuntimeError` (API/logic), `typer.Exit(code=1)` (CLI), `typer.Abort()` (user cancel)
- basedpyright strict — suppress with `# pyright: ignore[ruleCode]` (NOT `# type: ignore`)
- Lazy imports inside CLI command functions (keeps `cass --help` fast)
- `TYPE_CHECKING` guard for type-only imports in CLI modules

## Gotchas

- `CanvasFile.content_type` uses `msgspec.field(name="content-type")` (hyphenated API field)
- Canvas assignment/tab IDs are strings, not ints
- GitHub Classroom URL `url_id` is the org ID, NOT the classroom API `gh_id` — cannot lookup by `url_id` directly

## Linear

Project: **cass** — Team: **Ejolly** (EJO)

```bash
linear list-issues --project "cass"
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2
linear save-issue --id EJO-321 --state "In Progress"
```
