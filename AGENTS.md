# AGENTS.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. DuckDB storage, Typer CLI, NiceGUI browser viewer.

## Architecture

CLI (`cass/cli/`) and viewer (`cass/viewer/`) are co-equal interfaces with near feature parity.
Both MUST delegate to the shared functional core — never duplicate business logic between them.

```
┌───────┐  ┌────────┐
│  CLI  │  │ Viewer │   ← thin interfaces (args parsing / UI only)
└───┬───┘  └───┬────┘
    └─────┬────┘
          ▼
┌─────────────────────┐
│   Functional Core   │   ← all business logic lives here
│ db.py  pull.py      │
│ canvas/{sync,client, │
│ matching,egrades}.py │
│ models/             │
└─────────┬───────────┘
          ▼
      ┌────────┐
      │ DuckDB │
      └────────┘
```

- DB queries → `db.py`, not CLI or viewer
- Canvas push/preview → `canvas/sync.py`
- If both interfaces need it, extract to core

## Commands

```bash
uv sync                    # install deps
uv run poe lint            # ruff format → ruff check → ty → basedpyright
uv run poe test            # pytest
uv run poe install         # uv tool install . --force
```

**Always run `uv run poe lint && uv run poe test` before finishing work.**

Use `symbex` for token-efficient code exploration (signatures, docstrings, structure):

```bash
symbex -s -d cass/             # all signatures
symbex '*Client*' -s -d cass/  # find classes/functions matching pattern
symbex --docs --public -d cass/ # public symbols with docstrings
symbex 'MyClass.method' -d cass/ # specific method source
```

## Gotchas

- DuckDB: no `INSERT OR REPLACE` with multiple UNIQUE constraints — use `INSERT ... ON CONFLICT (pk) DO UPDATE SET ...`
- `CanvasFile.content_type` uses `msgspec.field(name="content-type")` (hyphenated API field)
- Canvas assignment/tab IDs are strings, not ints
- basedpyright strict mode — suppress with `# pyright: ignore[ruleCode]` (NOT `# type: ignore`)
- Lazy imports inside CLI command functions (keeps `cass --help` fast)

## Style (where we differ from defaults)

- File header: `from __future__ import annotations` → `__docformat__ = "google"` → imports
- `msgspec.Struct` for all data models (not dataclasses/pydantic)
- API types: `GH`/`Canvas`-prefixed. Domain types: unprefixed
- Error handling: `SystemExit` (config), `RuntimeError` (API/logic), `typer.Exit(code=1)` (CLI), `typer.Abort()` (user cancel)
- `TYPE_CHECKING` guard for type-only imports in CLI modules

## Linear

Project: **cass** — Team: **Ejolly** (EJO)

```bash
linear list-issues --project "cass"
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2
linear save-issue --id EJO-321 --state "In Progress"
```
