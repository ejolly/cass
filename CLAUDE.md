# CLAUDE.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. DuckDB storage, Typer CLI, NiceGUI browser viewer.

## Setup

```bash
uv sync          # install deps
gh auth status   # verify GH CLI auth (if using GitHub Classroom)
```

## Dev

```bash
uv run poe lint            # ruff format → ruff check → ty → basedpyright
uv run poe test            # pytest
uv run poe install         # uv tool install . --force
uv run poe docs            # pdoc → docs/api/
```

**Always run before finishing work:** `uv run poe lint && uv run poe test`

Use `symbex` to explore the codebase token-efficiently (e.g. `symbex --docs --public -d cass/`).

---

## Key Gotchas

- DuckDB `INSERT OR REPLACE` fails with multiple UNIQUE constraints — use `INSERT ... ON CONFLICT (pk) DO UPDATE SET ...`
- `CanvasSubmissionResponse` (API type) vs `CanvasSubmission` (domain type) — different structs
- `CanvasFile.content_type` uses `msgspec.field(name="content-type")` (hyphenated API field)
- Canvas assignment IDs are strings in GraphQL variables
- Canvas tab IDs are strings, not ints
- basedpyright strict mode — use `# pyright: ignore[ruleCode]` (NOT `# type: ignore`)

## Python Style

- `from __future__ import annotations` → `__docformat__ = "google"` → imports
- Google-style docstrings on public functions; `msgspec.Struct` for all data models
- `X | None` not `Optional[X]`; lowercase generics; `_prefixed` private
- API types: `GH`-prefixed / `Canvas`-prefixed. Domain types: unprefixed
- Lazy imports inside CLI command functions (fast startup)
- `TYPE_CHECKING` guard for type-only imports in CLI modules
- Error handling: `SystemExit` (config), `RuntimeError` (API/logic), `typer.Exit(code=1)` (CLI), `typer.Abort()` (user cancel)

## Project Management (Linear)

Project: **cass** — Team: **Ejolly** (EJO)

```bash
linear list-issues --project "cass"
linear get-issue --id EJO-321
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2 --description "..."
linear save-issue --id EJO-321 --state "In Progress"
# Priority: 1=Urgent, 2=High, 3=Medium, 4=Low
# States: Backlog, Todo, In Progress, Done, Canceled
```
