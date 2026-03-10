# TypeScript + Bun Migration Plan

Full rewrite of cass (excluding viewer) from Python to TypeScript, using Bun as the runtime/package manager.

## Tech Stack

| Concern | Python (current) | TypeScript (target) |
|---|---|---|
| Runtime | CPython 3.12 | Bun |
| CLI framework | Typer + Rich | cac |
| Shell/subprocess | subprocess | zx |
| HTTP client | httpx | ky (Canvas), `gh api` via zx (GitHub) |
| Database | sqlite-utils | drizzle-orm + drizzle-kit (SQLite via bun:sqlite) |
| Schema/validation | msgspec.Struct | zod |
| Serialization | msgspec | zod + native JSON |
| Config | tomllib (stdlib) | @iarna/toml or smol-toml |
| Output formatting | Rich tables/panels | @clack/prompts + chalk + cli-table3 |
| Task runner | poethepoet | bun scripts (package.json) |
| Linting | ruff | biome (format + lint) |
| Type checking | basedpyright + ty | tsc --noEmit (strict) |
| Testing | pytest | bun:test |
| Async | asyncio + httpx | native async/await + ky |

## Directory Structure (target)

```
cass/
├── src/
│   ├── index.ts              # CLI entry point (cac app)
│   ├── cli/
│   │   ├── index.ts          # Root commands (status, init, pull, push, etc.)
│   │   ├── canvas.ts         # Canvas subcommands
│   │   └── report.ts         # Reporting helpers
│   ├── db/
│   │   ├── connection.ts     # bun:sqlite connection (lazy singleton)
│   │   ├── schema.ts         # drizzle table definitions
│   │   ├── migrate.ts        # drizzle-kit migrations
│   │   ├── catalog.ts        # Table capabilities metadata
│   │   ├── queries.ts        # Enriched queries & dataset builders
│   │   ├── sync.ts           # Change tracking (shadow tables)
│   │   ├── introspection.ts  # Table inspection & cell updates
│   │   ├── views.ts          # Gradebook matrix
│   │   └── cache.ts          # Request-level caching
│   ├── apis/
│   │   ├── canvas/
│   │   │   ├── client.ts     # ky instance with retry, pagination, rate-limit
│   │   │   ├── schema.ts     # zod schemas for Canvas API responses
│   │   │   ├── matching.ts   # Roster & submission fetching
│   │   │   ├── egrades.ts    # Gradebook CSV import/export
│   │   │   └── sync.ts       # Grade push workflow
│   │   └── github/
│   │       ├── client.ts     # zx wrapper around `gh api` calls
│   │       ├── schema.ts     # zod schemas for GitHub API responses
│   │       ├── classroom.ts  # Classroom integration
│   │       ├── service.ts    # Higher-level operations
│   │       └── fetch.ts      # Repo cloning via zx (git clone/fetch)
│   ├── actions/
│   │   ├── config.ts         # TOML config loading (cass.toml)
│   │   ├── pull.ts           # Pull orchestration
│   │   ├── matching.ts       # Slug/name normalization
│   │   └── doctor.ts         # Prerequisite checks
│   └── utils/
│       ├── async.ts          # Bounded concurrency helper
│       └── format.ts         # Rich-like output helpers (chalk + tables)
├── tests/
│   ├── db/
│   ├── apis/
│   ├── actions/
│   └── fixtures/             # Shared test data
├── drizzle/                  # Generated migration files
├── package.json
├── tsconfig.json
├── biome.json
├── drizzle.config.ts
├── bunfig.toml               # Bun config (if needed)
└── CLAUDE.md                 # Updated dev instructions
```

## Migration Phases

### Phase 0: Project Scaffolding
- [ ] Initialize bun project (`bun init`)
- [ ] Install dependencies: `cac`, `zx`, `drizzle-orm`, `better-sqlite3` (or use `bun:sqlite` driver), `drizzle-kit`, `zod`, `ky`, `chalk`, `cli-table3`, `@clack/prompts`, `smol-toml`
- [ ] Dev dependencies: `@types/bun`, `biome`, `typescript`
- [ ] Configure `tsconfig.json` (strict, ESNext, bundler module resolution)
- [ ] Configure `biome.json` (format + lint rules mirroring current ruff config)
- [ ] Set up `package.json` scripts: `dev`, `build`, `lint`, `test`, `typecheck`
- [ ] Add `bin` entry to package.json for `cass` CLI
- [ ] Stub out directory structure with empty files

### Phase 1: Database Layer (`src/db/`)
This is the foundation — everything else depends on it.

- [ ] **schema.ts** — Define all drizzle table schemas matching SQLite v15:
  - `meta`, `students`, `assignments`
  - `canvas_students`, `canvas_assignments`, `canvas_submissions`, `canvas_grades`
  - `_canvas_assignments_synced`, `_canvas_grades_synced`
  - `gh_students`, `gh_assignments`, `gh_submissions`
  - Proper indexes and constraints
- [ ] **connection.ts** — Lazy singleton using `bun:sqlite` + drizzle
  - `dbPath()` — Locate `cass.db` relative to `cass.toml`
  - `getDb()` — Lazy-loaded drizzle instance
  - `initSchema()` — Run migrations or push schema
  - `reset()` — Close connection for delete/restore
- [ ] **migrate.ts** — drizzle-kit migration setup
- [ ] **catalog.ts** — Port `TABLE_CAPABILITIES` and `CANVAS_PUSHABLE` maps
- [ ] **queries.ts** — Port enriched queries and dataset builders
  - `students`, `assignments`, `submissions`, `gradebook` datasets
  - JOIN-based enriched queries for canvas_submissions, canvas_grades, etc.
- [ ] **sync.ts** — Port change tracking:
  - `snapshotCanvasSynced()`, `getPendingChanges()`, `canvasPreview()`, `canvasApply()`, `revertChanges()`
- [ ] **introspection.ts** — Port table inspection
- [ ] **views.ts** — Port gradebook matrix builder
- [ ] **cache.ts** — Port request caching with TTL
- [ ] Write tests for all db modules

### Phase 2: Zod Schemas (`src/apis/*/schema.ts`)
Define all API response types with zod — these replace msgspec.Struct.

- [ ] **Canvas schemas** — Port all types from `apis/canvas/schema.py`:
  - `CanvasCourse`, `CanvasStudentResponse`, `CanvasSubmissionResponse`
  - `CanvasAssignmentResponse`, `CanvasModule`, `CanvasModuleItem`
  - `CanvasQuiz`, `CanvasFolder`, `CanvasFile` (note: `content-type` hyphenated field)
  - `CanvasAnnouncement`, `CanvasUser`, `CanvasEnrollment`, `CanvasTab`
  - Use `z.transform()` for field renames (e.g., `content-type` → `contentType`)
- [ ] **GitHub schemas** — Port all types from `apis/github/schema.py`:
  - `GHStudentInfo`, `GHAssignmentResponse`, `GHAcceptedAssignment`
  - `GHRepository`, `GHStudentRef`, `GHStarterCodeRepo`, `GHCommit`
- [ ] **Domain schemas** — Port `db/schema.py` internal types:
  - `Student`, `Assignment`, `CanvasStudent`, `GHStudent`, etc.

### Phase 3: API Clients (`src/apis/`)

- [ ] **Canvas client** (`apis/canvas/client.ts`):
  - ky instance with: base URL from config, Bearer token auth, retry (3 attempts), rate-limit throttle
  - Pagination helper (Canvas uses `Link` header)
  - Methods: `getCourse()`, `listStudents()`, `listAssignments()`, `listSubmissions()`, `pushGrade()`, `listModules()`, `createModule()`, `publish()`, `unpublish()`, `deleteModule()`, `listUsers()`, `listFiles()`, `uploadFile()`, `listQuizzes()`, `listAnnouncements()`, `listTabs()`, etc.
  - All responses validated through zod schemas
- [ ] **Canvas matching** (`apis/canvas/matching.ts`):
  - `fetchStudents()`, `fetchStudentsWithSections()`, `fetchCanvasAssignments()`, `fetchCanvasSubmissions()`, `fetchCourseName()`, `pushGrade()`
- [ ] **Canvas sync/egrades** — Port as needed
- [ ] **GitHub client** (`apis/github/client.ts`):
  - All calls via `zx`: `await $\`gh api /path --paginate\``
  - Parse JSON responses through zod schemas
  - `checkAvailable()` — `which gh`
  - `checkAuth()` — `gh auth status`
  - Pagination via `--paginate` flag
- [ ] **GitHub classroom** (`apis/github/classroom.ts`):
  - `fetchAssignments()`, `fetchRoster()`, `fetchSubmissions()`, `buildRepoMap()`, `resolveGhId()`
- [ ] **GitHub fetch** (`apis/github/fetch.ts`):
  - Repo cloning via zx: `await $\`git clone ...\``
  - `sanitizeStudentDir()`, bounded concurrent cloning
- [ ] **GitHub service** (`apis/github/service.ts`)
- [ ] Write tests for API layer (mock ky/zx responses)

### Phase 4: Actions Layer (`src/actions/`)

- [ ] **config.ts** — Port `cass.toml` loading:
  - Use `smol-toml` for parsing, zod for validation
  - `getConfig()` singleton, `updateConfig()`, `parseCanvasCourseUrl()`
  - Walk-up directory search for `cass.toml`
- [ ] **pull.ts** — Port pull orchestration:
  - `pullStudents()`, `pullAssignments()`, `pullSubmissions()`
  - Bounded concurrent GitHub fetching
- [ ] **matching.ts** — Port `slugify()`, `slugMatch()`
- [ ] **doctor.ts** — Port prerequisite checks (gh CLI, Canvas token, config)
- [ ] Write tests for actions

### Phase 5: CLI Layer (`src/cli/`)

- [ ] **index.ts** — Entry point with cac:
  ```ts
  import cac from 'cac'
  const cli = cac('cass')
  cli.command('status', 'Show project sync status').action(statusCmd)
  cli.command('init', 'Initialize local setup').action(initCmd)
  // ... etc
  cli.help()
  cli.version(version)
  cli.parse()
  ```
- [ ] Port root commands:
  - `status` — Show sync overview
  - `init` — Interactive setup (Canvas token, Classroom URL)
  - `pull` — Fetch APIs → DB (with `--students`, `--assignments`, `--submissions`, `--limit`)
  - `push` — Preview + push Canvas changes (with `--yes`)
  - `revert` — Revert pending changes (with `--yes`)
  - `query <dataset>` — Query datasets (with `--where`, `--order`, `--limit`, `--sql`)
  - `pull-repos` — Clone/update repos (with `-a`, `-s`, `-n`)
  - `delete` — Delete DB (with `--yes`)
  - `backup` — Timestamped backup (with `--tag`, `--list`)
  - `restore <file>` — Restore from backup (with `--yes`)
  - Global: `--no-cache`, `--ttl`, `--version`
- [ ] **canvas.ts** — Port all canvas subcommands:
  - `canvas` (default: course overview)
  - `canvas people`, `canvas modules`, `canvas assignments`, `canvas quizzes`, `canvas files`, `canvas announcements`, `canvas tabs`, `canvas sync`
  - All CRUD subcommands (create, publish, unpublish, delete)
  - `--csv`, `--save` export options
- [ ] **report.ts** — Port reporting helpers
- [ ] Output formatting: chalk for colors, cli-table3 for tables, @clack/prompts for interactive prompts (confirm, select)

### Phase 6: Testing & Polish

- [ ] Ensure all `bun test` passes
- [ ] `bun run lint` (biome) passes clean
- [ ] `bun run typecheck` (tsc --noEmit) passes clean
- [ ] Test CLI end-to-end with a real `cass.toml` config
- [ ] Update `CLAUDE.md` with new dev instructions
- [ ] Verify `bun link` or `bun install -g .` makes `cass` available globally
- [ ] Remove Python files from branch (pyproject.toml, uv.lock, cass/ Python package, etc.)

## Key Design Decisions

### cac CLI structure (flat commands)
All commands are flat with hyphen-separated names. Examples:
```ts
cli.command('status', 'Show project sync status')
cli.command('init', 'Initialize local setup')
cli.command('pull', 'Fetch from APIs and update DB')
cli.command('canvas', 'Canvas course overview')
cli.command('canvas-people', 'Show course roster')
cli.command('canvas-modules', 'List modules')
cli.command('canvas-modules-create <name>', 'Create a module')
cli.command('canvas-modules-publish <id>', 'Publish a module')
cli.command('canvas-assignments', 'List assignments')
cli.command('canvas-assignments-create <name>', 'Create an assignment')
// etc.
```
Group related commands via description prefixes for readability in `--help`.

### drizzle + bun:sqlite
Drizzle has a `bun-sqlite` driver. Schema is defined in TypeScript (not SQL), and drizzle-kit generates migrations. The current Python app uses `sqlite-utils` which is more dynamic — drizzle is more structured but requires schema-first definitions.

For introspection-heavy code (dynamic table inspection, cell updates), we may need to drop to raw SQL via `db.run()` alongside drizzle's typed queries.

### zod vs msgspec
zod `.parse()` replaces `msgspec.convert()`. Key differences:
- zod does runtime validation + type inference (`z.infer<typeof Schema>`)
- Use `z.object({}).transform()` for field renaming (Canvas `content-type`)
- zod is ~10x slower than msgspec but fine for CLI use

### GitHub API via `gh api`
All GitHub calls go through zx:
```ts
const result = await $`gh api /classrooms/${id}/assignments --paginate`
const data = GHAssignmentSchema.array().parse(JSON.parse(result.stdout))
```
This keeps auth simple (gh handles it) and avoids token management entirely.

## Resolved Decisions

1. **cac with flat commands** — Canvas subcommands become flat: `cass canvas-modules-create`, `cass canvas-assignments-publish`, etc. Keep cac for its simplicity. Group related commands via help text/descriptions.

2. **Clean DB break** — No backward compatibility with Python-created `cass.db`. Users re-run `cass pull` after switching. Drizzle owns the schema from the start.

3. **Config compatibility** — `cass.toml` format stays the same. The TS version reads the same config file.

4. **Package name** — Keep `cass`. The branch is the boundary.
