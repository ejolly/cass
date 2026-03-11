# TypeScript + Bun Migration Plan

Full rewrite of cass (excluding viewer) from Python to TypeScript, using Bun as the runtime/package manager.

## Tech Stack

| Concern | Choice |
|---|---|
| Runtime | Bun |
| CLI framework | cac (flat commands) |
| Shell/subprocess | Bun.$ (native) |
| HTTP client | ky (Canvas), `gh api` via Bun.$ (GitHub) |
| Database | kysely (typed query builder, bun:sqlite dialect) |
| Schema/validation | zod (type + validation + transforms in one artifact) |
| Pattern matching | ts-pattern (exhaustive dispatch) |
| Config | smol-toml + zod schema |
| Terminal output | consola (logs/spinners/boxes) + cli-table3 (tables) |
| Interactive prompts | @clack/prompts |
| CSV | papaparse (parse + stringify) |
| File I/O | Bun.file(), Bun.write() (native) |
| Concurrency | p-limit + Promise.all |
| Linting | biome (format + lint) |
| Type checking | tsc --noEmit (strict) |
| Testing | bun:test |

## Completed Work (Phases 0–4)

### Phase 0+1: Scaffolding + Database Layer ✅
- Bun project with tsconfig (strict, ESNext, bundler resolution), biome, package.json scripts
- `src/db/schema.ts` — Kysely `Database` interface, 8 tables (simplified from 12), Selectable/Insertable/Updateable aliases
- `src/db/connection.ts` — lazy singleton, `createDb`, `getDb`, `closeDb`, `dbPath`
- `src/db/catalog.ts` — `TABLE_CAPABILITIES` record, `CANVAS_PUSHABLE`, helper functions
- `src/db/queries.ts` — typed queries with ts-pattern `.exhaustive()` dataset dispatch
- `src/db/sync.ts` — inline `_synced_*` column diff/revert (no shadow tables)
- `src/db/introspection.ts` — dynamic `updateTable`, `rawQuery`, `getTableColumns`
- `migrations/001_initial.ts` — schema v16
- Tests for all db modules (106 tests passing)

### Phase 2+3: Zod Schemas + API Clients ✅
- `src/apis/canvas/schema.ts` — 20+ Canvas zod schemas with transforms
- `src/apis/canvas/client.ts` — ky instance, pagination, `waitForProgress` (ts-pattern), `loadCanvasToken`, `resolveResource`
- `src/apis/canvas/matching.ts` — roster/submission fetch with section lookups
- `src/apis/canvas/egrades.ts` — UCSD eGrades CSV via shared `utils/csv.ts`
- `src/apis/canvas/sync.ts` — grade/assignment push workflow, `PushResult` discriminated union
- `src/apis/github/client.ts` — thin Bun.$ wrappers (`ghApi`, `ghApiList`, `checkAvailable`, `checkAuth`)
- `src/apis/github/schema.ts` — GitHub zod schemas
- `src/apis/github/classroom.ts` — classroom operations, `assignmentsToDB`, `studentsToDB`
- `src/apis/github/fetch.ts` — repo cloning via Bun.$ + p-limit

### Phase 4: Actions Layer ✅
- `src/actions/config.ts` — `TomlConfigSchema` (full Zod), `loadConfig`, `getConfig`, `updateConfig` with declarative field map, URL parsers, `ConfigState` discriminated union
- `src/actions/pull.ts` — pull orchestration with Kysely typed batch upserts (500 rows/batch)
- `src/actions/matching.ts` — `slugify`, `slugMatch`, `normalize`, `matchStudents`, `findCandidates`
- `src/actions/doctor.ts` — prerequisite checks with ts-pattern classroomStatus dispatch

### Post-Phase 4 Refactoring ✅
- Fixed `revertGrades` bug (was reading empty table after DELETE)
- Converted all raw SQL to Kysely typed writes (pull.ts, sync.ts)
- Added batch inserts via generic `batchUpsert()` helper
- Extracted `findProjectRoot` to `src/utils/paths.ts` (was duplicated), made async
- Added full Zod `TomlConfigSchema` replacing manual String()/Number() casts
- Removed stale `motherduckDb` / `[database]` config section
- Fixed variable shadowing, dynamic imports, directory detection issues

### Schema Simplification (v15 → v16) ✅
- **Merged `canvas_grades` into `canvas_submissions`** — added `posted_grade`, `grade_updated_at` columns; eliminated separate grades table
- **Merged `canvas_students` into `students`** — added `sortable_name`, `login_id`, `sis_user_id`, `sis_section_id` columns; one master student table
- **Replaced shadow tables with inline `_synced_*` columns** — `_synced_posted_grade` on `canvas_submissions`, `_synced_name`/`_synced_points_possible`/`_synced_due_at`/`_synced_published` on `canvas_assignments`
- Eliminated 4 tables: `canvas_grades`, `canvas_students`, `_canvas_grades_synced`, `_canvas_assignments_synced`
- Snapshot = `UPDATE SET _synced_x = x` (was DELETE ALL + INSERT SELECT)
- Diff = `WHERE x != _synced_x` (was LEFT JOIN across tables)
- Revert = `UPDATE SET x = _synced_x` (was DELETE ALL + INSERT SELECT)

### Shared Utilities
- `src/utils/paths.ts` — `findProjectRoot` (async, walks up looking for `cass.toml`)
- `src/utils/csv.ts` — thin papaparse wrappers (`parseCsv`, `toCsv`, `toCsvWithColumns`)

## Current State

- **131 tests passing**, lint clean, typecheck clean
- Schema v16: 8 tables (down from 12), no shadow tables
- Full CLI implemented: 40+ flat commands via cac, binary name `cassa`
- `src/db/views.ts` (gradebook matrix pivot) and `src/db/cache.ts` (request caching) not yet implemented
- `src/apis/github/service.ts` not yet implemented (may not be needed — classroom.ts covers it)

## Config Model

User provides two URLs during `cass init`:
1. **Canvas course URL** → derives `base_url` + `course_id` via `parseCanvasCourseUrl()`
2. **GitHub Classroom URL** (optional) → derives `url_id` via `parseClassroomUrl()`, resolves `gh_id` via GH API

Minimal `cass.toml`:
```toml
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335

[classroom]
url = "https://classroom.github.com/classrooms/232475786-201b-w26"
url_id = 232475786
gh_id = 299058
slug = "201b-w26"
title = "201b-W26"
```

Config fields: `slug`, `title`, `org` are populated during classroom resolution and used for display in `status`/`init`. `canvasModules` and `canvasAssignments` are optional TOML arrays used by `canvas-sync`.

### Phase 5: CLI Layer ✅
- `src/index.ts` — cac entry point (`cassa`), flat command registration, auto-help on no args
- `src/cli/index.ts` — 10 root commands: status, init, pull, push, revert, query, pull-repos, delete, backup, restore
- `src/cli/canvas.ts` — 30+ canvas commands: course overview, people, modules (CRUD), assignments (CRUD + groups), quizzes (CRUD), files (list/upload/delete), announcements (CRUD), tabs (show/hide), canvas-sync (dry-run/push)
- `src/cli/report.ts` — formatTable (cli-table3), formatCsv (papaparse), formatMarkdown (GFM), formatRows dispatcher
- All list commands support `--csv` and `--save` output formats
- 25 CLI tests (subprocess-based: help, version, status, query, push, revert, backup, delete)
- Binary name: `cassa` (avoids conflict with Python `cass`)

### Phase 6: Testing & Polish ✅
- [x] `src/db/views.ts` — not needed; `queryGradebook()` in `queries.ts` handles it
- [x] `src/db/cache.ts` — not needed; nothing references it
- [x] Update `CLAUDE.md` with TS dev instructions
- [x] Verify `bun link` / global install for `cassa` — works (`node_modules/.bin/cassa`; global requires `~/.cache/.bun/bin` in PATH)
- [x] Remove Python files from branch — removed `cass/{apis,cli,actions,db}`, `pyproject.toml`, `uv.lock`; kept `cass/viewer/` (NiceGUI frontend)

## Key Design Decisions

1. **cac with flat commands** — `cass canvas-modules-create`, not nested subcommands
2. **kysely over drizzle** — typed query builder handles both static CRUD and dynamic WHERE/ORDER/table names without escape hatches
3. **ts-pattern** — exhaustive dispatch for dataset routing, config state machine, push results, Canvas progress polling
4. **Clean DB break** — no backward compat with Python `cass.db`; users re-run `cass pull`
11. **Inline sync tracking** — `_synced_*` columns instead of shadow tables; simpler snapshot/diff/revert with no JOINs
12. **Merged tables** — `canvas_grades` → `canvas_submissions`, `canvas_students` → `students`; 8 tables instead of 12
5. **Config compatibility** — same `cass.toml` format, Zod-validated on load
6. **Bun natives** — Bun.$ (shell), Bun.file/write (I/O), bun:sqlite (DB), bun:test (tests)
7. **consola + cli-table3 + @clack/prompts** — logs/spinners, dense tables, interactive input
8. **gh CLI for GitHub** — `gh api --paginate` handles auth/pagination/rate-limiting natively
9. **ky for Canvas** — built-in retry + custom afterResponse hook for rate-limit throttling
10. **papaparse for CSV** — proper quoting for Canvas data with commas in names
