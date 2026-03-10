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
| Config | tomllib (stdlib) | smol-toml |
| Output formatting | Rich tables/panels | @clack/prompts + chalk + cli-table3 |
| Task runner | poethepoet | bun scripts (package.json) |
| Linting | ruff | biome (format + lint) |
| Type checking | basedpyright + ty | tsc --noEmit (strict) |
| Testing | pytest | bun:test |
| Async | asyncio + httpx | native async/await + ky |

## Stack Advantages Over 1:1 Port

This is not a line-for-line port. The TS stack eliminates significant boilerplate:

### Zod: one artifact = type + validation + transform
Python requires separate msgspec.Struct definitions (~40 across schema files) plus manual field handling. Zod collapses each to a single definition that gives you the runtime validator, the static type, and field transforms in one place:
```ts
const CanvasFile = z.object({
  id: z.number(),
  display_name: z.string(),
  'content-type': z.string(),
}).transform(({ 'content-type': contentType, ...rest }) => ({ ...rest, contentType }))
type CanvasFile = z.infer<typeof CanvasFile>  // no separate type definition needed
```

### Drizzle relational queries replace hand-built JOINs
The Python `queries.py` has ~200 lines of manual SQL string builders for enriched datasets (submissions with student names, gradebook JOINs, etc.). Drizzle's relational API handles this declaratively:
```ts
const submissions = await db.query.canvasSubmissions.findMany({
  with: { student: true, assignment: true },
  where: gt(canvasSubmissions.score, 0),
})
```
The gradebook pivot is still manual, but the JOIN builders disappear.

### Drizzle diffs replace row-by-row shadow table comparison
Python `sync.py` copies tables and compares row-by-row. Drizzle expresses the diff as a single query:
```ts
const pending = await db.select()
  .from(canvasGrades)
  .leftJoin(canvasGradesSynced, eq(canvasGrades.id, canvasGradesSynced.id))
  .where(ne(canvasGrades.score, canvasGradesSynced.score))
```

### `gh api --paginate` eliminates the GitHub client
The Python GitHub client (~150 lines) has async pagination with Link header parsing, bounded concurrency via `gather_bounded()`, and manual token management. All of this goes away — `gh` handles pagination, auth, and rate limiting natively. The entire client becomes ~20 lines of zx wrappers.

### ky hooks replace hand-rolled Canvas retry/throttle
The Python Canvas client has ~80 lines of retry logic, rate-limit detection, and exponential backoff. ky has this built in:
```ts
const canvas = ky.create({
  prefixUrl: config.canvasBaseUrl,
  retry: { limit: 3, backoffLimit: 8000 },
  hooks: { afterResponse: [throttleOnRateLimit] },
})
```
Only the pagination helper (~15 lines for Canvas `Link` headers) needs custom code.

### Native `Promise.all` replaces asyncio ceremony
`pull-repos` concurrent cloning goes from a custom `gather_bounded()` helper + asyncio event loop to:
```ts
const limit = pLimit(10)
await Promise.all(repos.map(r => limit(() => $`git clone ${r.url} ${r.dest}`)))
```

### What stays roughly the same size
- TOML config loading — similar complexity either way
- Gradebook matrix pivot — manual regardless of ORM
- Canvas subcommand surface area — 30+ commands is 30+ commands
- Introspection / dynamic table ops — actually harder in drizzle (drop to raw `bun:sqlite` for `cass query --sql`)

### Expected result
~60-70% of the Python line count for equivalent functionality. Biggest wins in API clients and schema definitions. DB layer and canvas CRUD stay similar.

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
│   │   ├── schema.ts         # drizzle table definitions + zod domain types
│   │   ├── migrate.ts        # drizzle-kit migrations
│   │   ├── catalog.ts        # Table capabilities metadata
│   │   ├── queries.ts        # Drizzle relational queries (replaces manual JOINs)
│   │   ├── sync.ts           # Change tracking via drizzle diff queries
│   │   ├── introspection.ts  # Raw bun:sqlite for dynamic table ops
│   │   ├── views.ts          # Gradebook matrix pivot
│   │   └── cache.ts          # Request-level caching
│   ├── apis/
│   │   ├── canvas/
│   │   │   ├── client.ts     # ky instance with retry hooks + pagination helper
│   │   │   ├── schema.ts     # zod schemas (type + validation + transforms)
│   │   │   ├── matching.ts   # Roster & submission fetching
│   │   │   ├── egrades.ts    # Gradebook CSV import/export
│   │   │   └── sync.ts       # Grade push workflow
│   │   └── github/
│   │       ├── client.ts     # Thin zx wrappers over `gh api --paginate`
│   │       ├── schema.ts     # zod schemas for GitHub API responses
│   │       ├── classroom.ts  # Classroom integration
│   │       ├── service.ts    # Higher-level operations
│   │       └── fetch.ts      # Repo cloning via zx + p-limit concurrency
│   ├── actions/
│   │   ├── config.ts         # smol-toml + zod validated config
│   │   ├── pull.ts           # Pull orchestration
│   │   ├── matching.ts       # Slug/name normalization
│   │   └── doctor.ts         # Prerequisite checks
│   └── utils/
│       └── format.ts         # chalk + cli-table3 output helpers
├── tests/
│   ├── db/
│   ├── apis/
│   ├── actions/
│   └── fixtures/
├── drizzle/                  # Generated migration files
├── package.json
├── tsconfig.json
├── biome.json
├── drizzle.config.ts
└── CLAUDE.md
```

Note: no `utils/async.ts` — native `Promise.all` + `p-limit` replaces the custom `gather_bounded()` helper.

## Migration Phases

### Phase 0: Project Scaffolding
- [ ] Initialize bun project (`bun init`)
- [ ] Install dependencies: `cac`, `zx`, `drizzle-orm`, `drizzle-kit`, `zod`, `ky`, `chalk`, `cli-table3`, `@clack/prompts`, `smol-toml`, `p-limit`
- [ ] Dev dependencies: `@types/bun`, `biome`, `typescript`
- [ ] Configure `tsconfig.json` (strict, ESNext, bundler module resolution)
- [ ] Configure `biome.json` (format + lint rules mirroring current ruff config)
- [ ] Set up `package.json` scripts: `dev`, `build`, `lint`, `test`, `typecheck`
- [ ] Add `bin` entry to package.json for `cass` CLI
- [ ] Stub out directory structure with empty files

### Phase 1: Database Layer (`src/db/`)
Foundation — everything else depends on it.

- [ ] **schema.ts** — Drizzle table definitions matching SQLite v15 + zod domain types:
  - `meta`, `students`, `assignments`
  - `canvas_students`, `canvas_assignments`, `canvas_submissions`, `canvas_grades`
  - `_canvas_assignments_synced`, `_canvas_grades_synced`
  - `gh_students`, `gh_assignments`, `gh_submissions`
  - Drizzle `relations()` declarations for relational queries
  - Proper indexes and constraints
- [ ] **connection.ts** — Lazy singleton using `bun:sqlite` + drizzle
  - `dbPath()` — Locate `cass.db` relative to `cass.toml`
  - `getDb()` — Lazy-loaded drizzle instance
  - `initSchema()` — Run migrations or push schema
  - `reset()` — Close connection for delete/restore
- [ ] **migrate.ts** — drizzle-kit migration setup
- [ ] **catalog.ts** — Port `TABLE_CAPABILITIES` and `CANVAS_PUSHABLE` maps
- [ ] **queries.ts** — Drizzle relational queries replacing manual SQL builders:
  - `students`, `assignments`, `submissions`, `gradebook` datasets
  - Use `db.query.*.findMany({ with: { ... } })` instead of hand-built JOINs
- [ ] **sync.ts** — Change tracking via drizzle diff queries:
  - `snapshotCanvasSynced()`, `getPendingChanges()` (LEFT JOIN + WHERE ne), `canvasPreview()`, `canvasApply()`, `revertChanges()`
- [ ] **introspection.ts** — Raw `bun:sqlite` for dynamic table ops (inspect any table, update any cell)
- [ ] **views.ts** — Gradebook matrix pivot (manual, same as Python)
- [ ] **cache.ts** — Request caching with TTL
- [ ] Tests for all db modules

### Phase 2: Zod Schemas (`src/apis/*/schema.ts`)
Each schema = runtime validator + static type + field transforms. No separate type definitions.

- [ ] **Canvas schemas** — Single zod definition per API type:
  - `CanvasCourse`, `CanvasStudentResponse`, `CanvasSubmissionResponse`
  - `CanvasAssignmentResponse`, `CanvasModule`, `CanvasModuleItem`
  - `CanvasQuiz`, `CanvasFolder`, `CanvasFile` (`.transform()` for `content-type` → `contentType`)
  - `CanvasAnnouncement`, `CanvasUser`, `CanvasEnrollment`, `CanvasTab`
- [ ] **GitHub schemas** — Single zod definition per API type:
  - `GHStudentInfo`, `GHAssignmentResponse`, `GHAcceptedAssignment`
  - `GHRepository`, `GHStudentRef`, `GHStarterCodeRepo`, `GHCommit`
- [ ] **Domain schemas** — zod versions of `db/schema.py` internal types (if not already covered by drizzle `$inferSelect` types)

### Phase 3: API Clients (`src/apis/`)

- [ ] **Canvas client** (`apis/canvas/client.ts`):
  - ky instance with retry hooks + rate-limit throttle (replaces ~80 lines of manual retry/backoff):
    ```ts
    const canvas = ky.create({
      prefixUrl, headers: { Authorization: `Bearer ${token}` },
      retry: { limit: 3, backoffLimit: 8000 },
      hooks: { afterResponse: [throttleOnRateLimit] },
    })
    ```
  - Pagination helper (~15 lines, Canvas `Link` header parsing)
  - Methods: `getCourse()`, `listStudents()`, `listAssignments()`, `listSubmissions()`, `pushGrade()`, `listModules()`, `createModule()`, `publish()`, `unpublish()`, `deleteModule()`, `listUsers()`, `listFiles()`, `uploadFile()`, `listQuizzes()`, `listAnnouncements()`, `listTabs()`, etc.
  - All responses piped through zod `.parse()` (replaces `msgspec.convert()`)
- [ ] **Canvas matching** (`apis/canvas/matching.ts`):
  - `fetchStudents()`, `fetchStudentsWithSections()`, `fetchCanvasAssignments()`, `fetchCanvasSubmissions()`, `fetchCourseName()`, `pushGrade()`
- [ ] **Canvas sync/egrades** — Port as needed
- [ ] **GitHub client** (`apis/github/client.ts`) — ~20 lines of zx wrappers replacing ~150 lines:
  - `ghApi(path)` — `await $\`gh api ${path} --paginate\`` + zod parse
  - `checkAvailable()` — `which gh`
  - `checkAuth()` — `gh auth status`
  - No manual pagination, no token management, no retry logic
- [ ] **GitHub classroom** (`apis/github/classroom.ts`):
  - `fetchAssignments()`, `fetchRoster()`, `fetchSubmissions()`, `buildRepoMap()`, `resolveGhId()`
- [ ] **GitHub fetch** (`apis/github/fetch.ts`):
  - Repo cloning via zx + `p-limit` (replaces `gather_bounded`):
    ```ts
    const limit = pLimit(10)
    await Promise.all(repos.map(r => limit(() => $`git clone ${r.url} ${r.dest}`)))
    ```
  - `sanitizeStudentDir()`
- [ ] **GitHub service** (`apis/github/service.ts`)
- [ ] Tests for API layer (mock ky/zx responses)

### Phase 4: Actions Layer (`src/actions/`)

- [ ] **config.ts** — smol-toml parsing + zod validated config:
  - `getConfig()` singleton, `updateConfig()`, `parseCanvasCourseUrl()`
  - Walk-up directory search for `cass.toml`
- [ ] **pull.ts** — Pull orchestration:
  - `pullStudents()`, `pullAssignments()`, `pullSubmissions()`
  - Uses `p-limit` for concurrent GitHub fetching
- [ ] **matching.ts** — Port `slugify()`, `slugMatch()`
- [ ] **doctor.ts** — Prerequisite checks (gh CLI, Canvas token, config)
- [ ] Tests for actions

### Phase 5: CLI Layer (`src/cli/`)

- [ ] **index.ts** — cac entry point with flat commands:
  ```ts
  import cac from 'cac'
  const cli = cac('cass')
  cli.command('status', 'Show project sync status').action(statusCmd)
  cli.command('init', 'Initialize local setup').action(initCmd)
  cli.command('pull', 'Fetch from APIs and update DB').option('--students', '...').action(pullCmd)
  cli.command('canvas', 'Canvas course overview').action(canvasCmd)
  cli.command('canvas-people', 'Canvas: show course roster').action(canvasPeopleCmd)
  cli.command('canvas-modules', 'Canvas: list modules').action(canvasModulesCmd)
  cli.command('canvas-modules-create <name>', 'Canvas: create module').action(canvasModulesCreateCmd)
  // ...
  cli.help()
  cli.version(version)
  cli.parse()
  ```
- [ ] Port root commands:
  - `status` — Show sync overview
  - `init` — Interactive setup (@clack/prompts for text input, confirm, select)
  - `pull` — Fetch APIs → DB (with `--students`, `--assignments`, `--submissions`, `--limit`)
  - `push` — Preview + push Canvas changes (with `--yes`)
  - `revert` — Revert pending changes (with `--yes`)
  - `query <dataset>` — Query datasets (with `--where`, `--order`, `--limit`, `--sql`)
  - `pull-repos` — Clone/update repos (with `-a`, `-s`, `-n`)
  - `delete` — Delete DB (with `--yes`)
  - `backup` — Timestamped backup (with `--tag`, `--list`)
  - `restore <file>` — Restore from backup (with `--yes`)
  - Global: `--no-cache`, `--ttl`, `--version`
- [ ] **canvas.ts** — All canvas flat commands:
  - `canvas` (course overview), `canvas-people`, `canvas-modules`, `canvas-modules-create`, `canvas-modules-publish`, `canvas-modules-unpublish`, `canvas-modules-delete`, `canvas-modules-add-item`
  - `canvas-assignments`, `canvas-assignments-groups`, `canvas-assignments-create`, `canvas-assignments-publish`, `canvas-assignments-unpublish`, `canvas-assignments-delete`
  - `canvas-quizzes`, `canvas-quizzes-create`, `canvas-quizzes-publish`, `canvas-quizzes-unpublish`, `canvas-quizzes-delete`
  - `canvas-files`, `canvas-files-upload`, `canvas-files-delete`
  - `canvas-announcements`, `canvas-announcements-create`, `canvas-announcements-update`, `canvas-announcements-delete`
  - `canvas-tabs`, `canvas-tabs-show`, `canvas-tabs-hide`
  - `canvas-sync` (with `--push`, `--force`)
  - All list commands: `--csv`, `--save` export options
- [ ] **report.ts** — Reporting helpers
- [ ] Output: chalk for colors, cli-table3 for tables, @clack/prompts for interactive prompts

### Phase 6: Testing & Polish

- [ ] All `bun test` passes
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
Drizzle has a `bun-sqlite` driver. Schema is defined in TypeScript (not SQL), and drizzle-kit generates migrations. Relational queries (`db.query.*.findMany({ with })`) replace manual JOIN builders from the Python version.

For introspection-heavy code (dynamic table inspection, cell updates, `cass query --sql`), drop to raw `bun:sqlite` alongside drizzle's typed queries.

### zod: unified type + validation
`z.infer<typeof Schema>` gives you the static type for free. `.transform()` handles field renames. `.parse()` replaces `msgspec.convert()`. No separate type definitions needed — each API response is one zod object.

### GitHub API via `gh api`
All GitHub calls go through zx:
```ts
const result = await $`gh api /classrooms/${id}/assignments --paginate`
const data = GHAssignmentSchema.array().parse(JSON.parse(result.stdout))
```
This keeps auth simple (gh handles it) and avoids token management entirely. Eliminates ~130 lines of custom client code.

### Canvas client via ky hooks
ky's built-in retry + custom `afterResponse` hook for rate-limit throttling replaces ~80 lines of manual retry/backoff. Only the pagination helper (Canvas `Link` header) needs custom code (~15 lines).

### Concurrency via p-limit
`p-limit` replaces the custom `gather_bounded()` asyncio helper. Native `Promise.all` + a limiter is idiomatic JS.

## Resolved Decisions

1. **cac with flat commands** — Canvas subcommands become flat: `cass canvas-modules-create`, `cass canvas-assignments-publish`, etc. Keep cac for its simplicity. Group related commands via help text/descriptions.

2. **Clean DB break** — No backward compatibility with Python-created `cass.db`. Users re-run `cass pull` after switching. Drizzle owns the schema from the start.

3. **Config compatibility** — `cass.toml` format stays the same. The TS version reads the same config file.

4. **Package name** — Keep `cass`. The branch is the boundary.
