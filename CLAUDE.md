# CLAUDE.md — cass

CLI grading toolkit for Canvas LMS. SQLite storage, Typer CLI, NiceGUI browser viewer.

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
uv run poe ok            # formats, lints, tests
uv run poe install         # uv tool install . --force
```

**Always run `uv run poe ok` before finishing work.**

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
- The `cass.toml` points to a test Canvas course. When making canvas changes, ask the user if you should dogfood against it and clean up after yourself if granted permission.
