# TypeScript + Bun Migration Plan

Full rewrite of cass (excluding viewer) from Python to TypeScript, using Bun as the runtime/package manager.

## Tech Stack

| Concern | Python (current) | TypeScript (target) |
|---|---|---|
| Runtime | CPython 3.12 | Bun |
| CLI framework | Typer + Rich | cac |
| Shell/subprocess | subprocess | zx |
| HTTP client | httpx | ky (Canvas), `gh api` via zx (GitHub) |
| Database | sqlite-utils | kysely (typed query builder, bun:sqlite dialect) |
| Migrations | sqlite-utils | kysely-ctl (plain SQL migration files) |
| Schema/validation | msgspec.Struct | zod |
| Pattern matching | _(none)_ | ts-pattern (exhaustive dispatch) |
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

### Kysely: typed query builder that handles both static and dynamic SQL
The Python version uses sqlite-utils (dynamic) but needs manual SQL strings for JOINs and enriched queries (~200 lines in `queries.py`). Drizzle would require raw SQL escape hatches for ~40% of the DB layer (introspection, dynamic WHERE/ORDER, shadow diffs). Kysely is a typed query builder — not an ORM — that handles both cases natively:

**Static CRUD stays typed:**
```ts
await db.insertInto('ghStudents')
  .values({ githubUsername: s.login, githubId: s.id, name: s.name })
  .onConflict(oc => oc.column('githubUsername').doUpdateSet({ name: s.name }))
  .execute()
```

**Dynamic queries stay typed too (no raw SQL escape hatch needed):**
```ts
let query = db.selectFrom('canvasSubmissions as cs')
  .innerJoin('students as s', 's.canvasId', 'cs.canvasUserId')
  .innerJoin('assignments as a', 'a.canvasAssignmentId', 'cs.canvasAssignmentId')
  .select(['s.name', 'a.title', 'cs.score'])
if (where) query = query.where(sql.raw(where))  // CLI --where passthrough
if (order) query = query.orderBy(sql.raw(order))
if (limit) query = query.limit(limit)
```

**Shadow table diffs — typed JOINs instead of row-by-row comparison:**
```ts
const pending = await db.selectFrom('canvasGrades as g')
  .leftJoin('_canvasGradesSynced as s', join =>
    join.onRef('g.canvasUserId', '=', 's.canvasUserId')
        .onRef('g.canvasAssignmentId', '=', 's.canvasAssignmentId'))
  .where(({ or, cmpr }) => or([
    cmpr('g.postedGrade', '!=', ref('s.postedGrade')),
    cmpr('s.canvasUserId', 'is', null),
  ]))
  .selectAll('g')
  .execute()
```

**Dynamic introspection — `updateTable()` accepts variable table names:**
```ts
await db.updateTable(tableName)
  .set({ [column]: value })
  .where(pkCol, '=', pkValue)
  .execute()
```

### ts-pattern: exhaustive dispatch replaces untyped dict branching
The Python codebase has dense dispatch patterns using `.get()` chains, dict lookups, and if/elif cascades without compile-time exhaustiveness. ts-pattern provides exhaustive matching with `.exhaustive()`:

**Push result rendering** — replaces 30 lines of nested `result.get("ok")` / `result.get("action")` / `result.get("canvas_id")`:
```ts
type PushResult =
  | { ok: true; action: 'posted_to_students' }
  | { ok: true; canvasAssignmentId: number; count: number }
  | { ok: false; error: string; canvasId?: number }

match(result)
  .with({ ok: true, action: 'posted_to_students' }, () => log('grades now visible'))
  .with({ ok: true, canvasAssignmentId: P.number }, r => log(`${r.canvasAssignmentId}: ${r.count} grades`))
  .with({ ok: false }, r => failures.push(`${r.canvasId}: ${r.error}`))
  .exhaustive()
```

**Dataset query dispatch** — ensures adding a dataset forces handling everywhere:
```ts
type Dataset = 'students' | 'assignments' | 'submissions' | 'gradebook'
match(dataset)
  .with('students', 'assignments', () => renderTable(...))
  .with('submissions', () => renderQuery(...))
  .with('gradebook', () => renderMatrix(...))
  .exhaustive()  // compile error if a new dataset is added but not handled
```

**Config state machine** — replaces boolean combo checks in `init`:
```ts
type ConfigState =
  | { tag: 'configured'; ghId: number }
  | { tag: 'pending'; url: string; urlId: string }
  | { tag: 'missing' }

match(classroomState)
  .with({ tag: 'configured' }, s => log(`Classroom ${s.ghId} ready`))
  .with({ tag: 'pending' }, s => resolveClassroom(s.url))
  .with({ tag: 'missing' }, () => promptClassroomUrl())
  .exhaustive()
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
- Gradebook matrix pivot — manual regardless of query builder
- Canvas subcommand surface area — 30+ commands is 30+ commands

### Expected result
~55-65% of the Python line count for equivalent functionality. Biggest wins in API clients, schema definitions, and dispatch logic. DB layer is tighter thanks to kysely handling both static and dynamic cases without escape hatches.

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
│   │   ├── connection.ts     # bun:sqlite + kysely setup (lazy singleton)
│   │   ├── schema.ts         # kysely Database interface + zod domain types
│   │   ├── catalog.ts        # Table capabilities (typed with ts-pattern dispatch)
│   │   ├── queries.ts        # Kysely typed queries (JOINs, enriched datasets)
│   │   ├── sync.ts           # Change tracking via kysely diff JOINs
│   │   ├── introspection.ts  # Dynamic table ops via kysely (updateTable, etc.)
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
├── migrations/               # Plain SQL migration files (kysely-ctl)
├── package.json
├── tsconfig.json
├── biome.json
└── CLAUDE.md
```

Notes:
- No `utils/async.ts` — native `Promise.all` + `p-limit` replaces `gather_bounded()`
- No `drizzle/` or `drizzle.config.ts` — kysely uses plain SQL migrations via `kysely-ctl`
- No `introspection.ts` escape hatch to raw `bun:sqlite` — kysely handles dynamic table/column refs natively

## Migration Phases

### Phase 0: Project Scaffolding
- [ ] Initialize bun project (`bun init`)
- [ ] Install dependencies: `cac`, `zx`, `kysely`, `kysely-bun-sqlite`, `zod`, `ts-pattern`, `ky`, `chalk`, `cli-table3`, `@clack/prompts`, `smol-toml`, `p-limit`
- [ ] Dev dependencies: `@types/bun`, `biome`, `typescript`, `kysely-ctl`
- [ ] Configure `tsconfig.json` (strict, ESNext, bundler module resolution)
- [ ] Configure `biome.json` (format + lint rules mirroring current ruff config)
- [ ] Set up `package.json` scripts: `dev`, `build`, `lint`, `test`, `typecheck`, `migrate`
- [ ] Add `bin` entry to package.json for `cass` CLI
- [ ] Stub out directory structure with empty files

### Phase 1: Database Layer (`src/db/`)
Foundation — everything else depends on it.

- [ ] **schema.ts** — Kysely `Database` interface + zod domain types:
  - TypeScript interfaces for all tables matching SQLite v15:
    `Meta`, `Students`, `Assignments`, `CanvasStudents`, `CanvasAssignments`, `CanvasSubmissions`, `CanvasGrades`, `CanvasAssignmentsSynced`, `CanvasGradesSynced`, `GHStudents`, `GHAssignments`, `GHSubmissions`
  - Aggregate `Database` interface mapping table names → row types (kysely pattern)
  - Zod schemas for domain types where runtime validation is needed
- [ ] **connection.ts** — Lazy singleton using `bun:sqlite` + kysely
  - `dbPath()` — Locate `cass.db` relative to `cass.toml`
  - `getDb()` — Lazy-loaded `Kysely<Database>` instance
  - `initSchema()` — Run migrations via kysely-ctl
  - `reset()` — Close connection for delete/restore
- [ ] **migrations/** — Plain SQL files for schema v1 (matching Python v15)
- [ ] **catalog.ts** — `TABLE_CAPABILITIES` and `CANVAS_PUSHABLE` as typed const maps. Use ts-pattern for capability dispatch:
  ```ts
  const canEdit = (table: TableName) => match(table)
    .with('canvas_grades', 'canvas_assignments', () => true)
    .with('gh_students', () => true)  // only 'excluded' column
    .otherwise(() => false)
  ```
- [ ] **queries.ts** — Kysely typed queries replacing manual SQL builders:
  - `students`, `assignments`, `submissions`, `gradebook` datasets
  - Enriched queries as kysely `.selectFrom().innerJoin()` chains (type-safe, no raw SQL)
  - Dataset dispatch via ts-pattern `.exhaustive()`
- [ ] **sync.ts** — Change tracking via kysely LEFT JOIN + WHERE:
  - `snapshotCanvasSynced()` — `INSERT INTO ... SELECT FROM` via kysely
  - `getPendingChanges()` — LEFT JOIN synced table, WHERE fields differ
  - `canvasPreview()`, `canvasApply()`, `revertChanges()`
  - Push result types as discriminated unions, rendered with ts-pattern
- [ ] **introspection.ts** — Dynamic table ops via kysely:
  - `updateTable(name)` for variable table names
  - `sql.raw()` for the `cass query --sql` escape hatch only
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
  - `CanvasProgress` with workflow_state as `z.enum(['queued', 'running', 'completed', 'failed'])`
- [ ] **GitHub schemas** — Single zod definition per API type:
  - `GHStudentInfo`, `GHAssignmentResponse`, `GHAcceptedAssignment`
  - `GHRepository`, `GHStudentRef`, `GHStarterCodeRepo`, `GHCommit`
- [ ] **Domain schemas** — zod versions of `db/schema.py` internal types (if not already covered by kysely `Selectable<T>` types)

### Phase 3: API Clients (`src/apis/`)

- [ ] **Canvas client** (`apis/canvas/client.ts`):
  - ky instance with retry hooks + rate-limit throttle (replaces ~80 lines of manual retry/backoff)
  - Pagination helper (~15 lines, Canvas `Link` header parsing)
  - Methods: `getCourse()`, `listStudents()`, `listAssignments()`, `listSubmissions()`, `pushGrade()`, `listModules()`, `createModule()`, `publish()`, `unpublish()`, `deleteModule()`, `listUsers()`, `listFiles()`, `uploadFile()`, `listQuizzes()`, `listAnnouncements()`, `listTabs()`, etc.
  - All responses piped through zod `.parse()`
  - `waitForProgress()` uses ts-pattern to match on `workflowState`:
    ```ts
    match(progress.workflowState)
      .with('completed', () => progress)
      .with('failed', () => { throw new Error(progress.message) })
      .with('queued', 'running', () => sleep(1000))
      .exhaustive()
    ```
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
  - Repo cloning via zx + `p-limit`
  - `sanitizeStudentDir()`
- [ ] **GitHub service** (`apis/github/service.ts`)
- [ ] Tests for API layer (mock ky/zx responses)

### Phase 4: Actions Layer (`src/actions/`)

- [ ] **config.ts** — smol-toml parsing + zod validated config:
  - `getConfig()` singleton, `updateConfig()`, `parseCanvasCourseUrl()`
  - Walk-up directory search for `cass.toml`
  - Config state as discriminated union for ts-pattern matching in `init`
- [ ] **pull.ts** — Pull orchestration:
  - `pullStudents()`, `pullAssignments()`, `pullSubmissions()`
  - Uses `p-limit` for concurrent GitHub fetching
  - Pull mode as tagged union (`{ mode: 'all' } | { mode: 'students' } | ...`) instead of boolean flags
- [ ] **matching.ts** — Port `slugify()`, `slugMatch()`
- [ ] **doctor.ts** — Prerequisite checks (gh CLI, Canvas token, config)
  - Check results as discriminated union (ok | warn | error) with ts-pattern rendering
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
  - `push` — Preview + push Canvas changes (with `--yes`). Render results with ts-pattern `.exhaustive()`
  - `revert` — Revert pending changes (with `--yes`)
  - `query <dataset>` — Query datasets (with `--where`, `--order`, `--limit`, `--sql`). Dataset dispatch via ts-pattern
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
cli.command('canvas-modules-create <name>', 'Create a module')
```
Group related commands via description prefixes for readability in `--help`.

### kysely over drizzle
Kysely is a typed query builder (not an ORM). It's a better fit than drizzle because:
1. **No escape hatch needed** — dynamic WHERE/ORDER (`cass query --where`), variable table/column names (`updateTable(name)`), and shadow table diffs all work within kysely's typed API
2. **Closer to sqlite-utils** — both are query builders, not ORMs. The migration is more natural
3. **Plain SQL migrations** — `kysely-ctl` uses `.sql` files, simpler than drizzle-kit's codegen
4. **Type safety on dynamic ops** — `updateTable(tableName)` is typed via the `Database` interface; drizzle would need raw `bun:sqlite` for these
5. **Trade-off**: no drizzle-style `findMany({ with })` relational sugar. Kysely JOINs are explicit (~2 extra lines per query) but give full control over SELECT lists

### ts-pattern for dispatch
Three high-value areas:
1. **Push/pull result types** — Discriminated unions + `.exhaustive()` replace 30+ lines of nested `.get()` chains
2. **Dataset query dispatch** — Compile-time guarantee that all datasets are handled
3. **Config state machine** — `init` command's 3-state flow (configured/pending/missing) becomes explicit and exhaustive

Also used in: table capability dispatch (catalog), Canvas workflow state polling, doctor check rendering, change-tracking column handling.

### zod: unified type + validation
`z.infer<typeof Schema>` gives you the static type for free. `.transform()` handles field renames. `.parse()` replaces `msgspec.convert()`. No separate type definitions needed — each API response is one zod object.

### GitHub API via `gh api`
All GitHub calls go through zx. `gh` handles pagination, auth, and rate limiting. Eliminates ~130 lines of custom client code.

### Canvas client via ky hooks
ky's built-in retry + custom `afterResponse` hook for rate-limit throttling replaces ~80 lines of manual retry/backoff. Only the pagination helper (Canvas `Link` header) needs custom code (~15 lines).

### Concurrency via p-limit
`p-limit` replaces the custom `gather_bounded()` asyncio helper. Native `Promise.all` + a limiter is idiomatic JS.

## Resolved Decisions

1. **cac with flat commands** — Canvas subcommands become flat: `cass canvas-modules-create`, `cass canvas-assignments-publish`, etc.

2. **Clean DB break** — No backward compatibility with Python-created `cass.db`. Users re-run `cass pull` after switching. Kysely owns the schema from the start.

3. **Config compatibility** — `cass.toml` format stays the same. The TS version reads the same config file.

4. **Package name** — Keep `cass`. The branch is the boundary.

5. **kysely over drizzle** — Typed query builder fits better than ORM for a codebase with significant dynamic SQL needs.

6. **ts-pattern** — Added for exhaustive dispatch on result types, dataset routing, and config state machines.
