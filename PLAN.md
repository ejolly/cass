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
- `src/db/schema.ts` — Kysely `Database` interface, 12 table types, Selectable/Insertable/Updateable aliases
- `src/db/connection.ts` — lazy singleton, `createDb`, `getDb`, `closeDb`, `dbPath`
- `src/db/catalog.ts` — `TABLE_CAPABILITIES` record, `CANVAS_PUSHABLE`, helper functions
- `src/db/queries.ts` — typed queries with ts-pattern `.exhaustive()` dataset dispatch
- `src/db/sync.ts` — shadow table snapshot/diff/revert via Kysely typed writes
- `src/db/introspection.ts` — dynamic `updateTable`, `rawQuery`, `getTableColumns`
- `migrations/001_initial.ts` — schema v15
- Tests for all db modules (96 tests passing)

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

### Shared Utilities
- `src/utils/paths.ts` — `findProjectRoot` (async, walks up looking for `cass.toml`)
- `src/utils/csv.ts` — thin papaparse wrappers (`parseCsv`, `toCsv`, `toCsvWithColumns`)

## Current State

- **96 tests passing**, lint clean, typecheck clean
- `src/cli/` is empty — Phase 5 not started
- `src/index.ts` (CLI entry point) does not exist yet
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

## Remaining Work

### Phase 5: CLI Layer (`src/cli/`)

- [ ] **`src/index.ts`** — cac entry point, flat command registration, `cli.help()`, `cli.version()`, `cli.parse()`
- [ ] **Root commands** (`src/cli/index.ts`):
  - `status` — sync overview (consola.box for summary panel)
  - `init` — interactive setup (@clack/prompts: text for URLs, confirm, select). Uses `parseCanvasCourseUrl()`, `parseClassroomUrl()`, `updateConfig()`. ts-pattern for ConfigState dispatch
  - `pull` — fetch APIs → DB (`--students`, `--assignments`, `--submissions`, `--limit`). PullMode dispatch via ts-pattern. consola for progress
  - `push` — preview + push Canvas changes (`--yes`). Render PushResult with ts-pattern `.exhaustive()`
  - `revert` — revert pending changes (`--yes`)
  - `query <dataset>` — query datasets (`--where`, `--order`, `--limit`, `--sql`). cli-table3 for output
  - `pull-repos` — clone/update repos (`-a`, `-s`, `-n`)
  - `delete` — delete DB (`--yes`)
  - `backup` — `Bun.write(backupPath, Bun.file(dbPath))` (`--tag`, `--list`)
  - `restore <file>` — `Bun.write(dbPath, Bun.file(backupPath))` (`--yes`)
- [ ] **Canvas commands** (`src/cli/canvas.ts`):
  - `canvas` (course overview), `canvas-people`, `canvas-modules`, `canvas-modules-create`, `canvas-modules-publish`, `canvas-modules-unpublish`, `canvas-modules-delete`, `canvas-modules-add-item`
  - `canvas-assignments`, `canvas-assignments-groups`, `canvas-assignments-create`, `canvas-assignments-publish`, `canvas-assignments-unpublish`, `canvas-assignments-delete`
  - `canvas-quizzes`, `canvas-quizzes-create`, `canvas-quizzes-publish`, `canvas-quizzes-unpublish`, `canvas-quizzes-delete`
  - `canvas-files`, `canvas-files-upload`, `canvas-files-delete`
  - `canvas-announcements`, `canvas-announcements-create`, `canvas-announcements-update`, `canvas-announcements-delete`
  - `canvas-tabs`, `canvas-tabs-show`, `canvas-tabs-hide`
  - `canvas-sync` (`--push`, `--force`) — uses `cfg.canvasModules` / `cfg.canvasAssignments`
  - All list commands: `--csv` (papaparse), `--save` (Bun.write)
- [ ] **`src/cli/report.ts`** — shared table rendering (cli-table3), CSV/markdown export helpers

### Phase 6: Testing & Polish

- [ ] CLI end-to-end test with real `cass.toml`
- [ ] Implement `src/db/views.ts` (gradebook matrix pivot) if needed by `query gradebook`
- [ ] Implement `src/db/cache.ts` (request caching with TTL) if needed
- [ ] Update `CLAUDE.md` with TS dev instructions
- [ ] Verify `bun link` makes `cass` available globally
- [ ] Remove Python files from branch (pyproject.toml, uv.lock, cass/ Python package)

## Key Design Decisions

1. **cac with flat commands** — `cass canvas-modules-create`, not nested subcommands
2. **kysely over drizzle** — typed query builder handles both static CRUD and dynamic WHERE/ORDER/table names without escape hatches
3. **ts-pattern** — exhaustive dispatch for dataset routing, config state machine, push results, Canvas progress polling
4. **Clean DB break** — no backward compat with Python `cass.db`; users re-run `cass pull`
5. **Config compatibility** — same `cass.toml` format, Zod-validated on load
6. **Bun natives** — Bun.$ (shell), Bun.file/write (I/O), bun:sqlite (DB), bun:test (tests)
7. **consola + cli-table3 + @clack/prompts** — logs/spinners, dense tables, interactive input
8. **gh CLI for GitHub** — `gh api --paginate` handles auth/pagination/rate-limiting natively
9. **ky for Canvas** — built-in retry + custom afterResponse hook for rate-limit throttling
10. **papaparse for CSV** — proper quoting for Canvas data with commas in names
