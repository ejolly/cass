# CLAUDE.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. TypeScript + Bun runtime. SQLite storage. Binary: `cassa`.

## Architecture

CLI (`src/cli/`) is a thin interface over a shared functional core.
**Never** put business logic, data transforms, queries, or API calls in CLI code.
Use existing models (`db/schema.ts`, `apis/*/schema.ts`), operations (`db/`, `apis/`, `actions/`), and catalog metadata (`db/catalog.ts`). If it doesn't exist in core, add it there first.

```
CLI (src/cli/)  →  actions/  →  db/     →  SQLite (bun:sqlite)
                    apis/       catalog
```

The viewer (`cass/viewer/`) is a separate Python/NiceGUI app — do not modify it as part of TS work.

## Commands

```bash
bun install                # install deps
bun run lint               # biome check
bun run lint:fix           # biome check --write
bun run typecheck          # tsc --noEmit (root + cassa/)
bun test                   # bun:test
bun run check              # lint + typecheck + test (all-in-one)
bun run dev                # run CLI in dev mode
bun run build              # compile to dist/cassa
```

**Always run `bun run check` before finishing work.**

## Style

### Functions
- Top-level: always `function` keyword declarations, never arrow assignments
- Arrows only for inline callbacks (`.map()`, `.filter()`, `.find()`)
- All exports are named — no default exports
- Pure by default: core functions (`db/`, `actions/`, `apis/`) must not call `consola` or do I/O. Accept `onProgress?: ProgressFn` callbacks for reporting

### Data Flow
- `const` by default; `let` only when reassignment is unavoidable; never `var`
- Prefer `.map()` / `.filter()` / `.find()` chains over imperative loops
- `for...of` only for sequential async (rate-limiting) or building Maps
- Build collections with spread/concat, not `.push()` into mutable arrays (unless accumulating in a sequential loop)
- Object construction via spread and `Object.fromEntries` — avoid in-place mutation

### Control Flow
- `ts-pattern` `.match().with().exhaustive()` for discriminated unions — never `.otherwise()` for exhaustive types
- `switch` for simple string-literal dispatch (e.g., output format)
- Early `return` for guards; ternary for inline conditionals; no nested if/else ladders

### Types
- Zod schemas for API responses; `type` = `z.infer<typeof Schema>` (co-located, same name)
- API types: `Canvas`/`GH`-prefixed Zod schemas
- `interface` for internal domain/config types
- `type` for discriminated unions, Kysely row aliases, computed types
- Generics only where truly needed — no premature abstraction

### Side Effects & State
- Side effects are layered: DB writes in `db/`, API calls in `apis/`, console output in `cli/` only
- Errors: `process.exit(1)` (fatal CLI), `throw Error` (logic), `consola.error` (display)
- Two allowed singletons: `_db` (connection.ts), `_cached` (config.ts) with explicit reset functions. No other module-level mutable state

### Module Organization
- Barrel `index.ts` re-exports per directory; `export type { ... }` separated from value exports
- `@/` path alias for cross-module imports
- Lazy dynamic imports in CLI command handlers for startup performance
- Section dividers: `// ─── Title ──────────` within files

### Tooling
- Biome for formatting + linting (2-space indent, 100 char line width)
- Kysely typed query builder — no raw SQL

## Key Libraries

| Concern | Choice |
|---|---|
| Runtime | Bun |
| CLI framework | cac (flat commands) |
| Shell/subprocess | Bun.$ |
| HTTP client | ky (Canvas), `gh api` via Bun.$ (GitHub) |
| Database | kysely + bun:sqlite |
| Schema/validation | zod |
| Pattern matching | ts-pattern |
| Config | smol-toml + zod |
| Terminal output | consola + cli-table3 |
| Interactive prompts | @clack/prompts |
| CSV | papaparse |
| Concurrency | p-limit + Promise.all |

## Gotchas

- Canvas assignment/tab IDs are strings, not ints
- GitHub Classroom `url_id` is the org ID, NOT the classroom API `gh_id` — cannot lookup by `url_id` directly
- `gh api --paginate` handles auth/pagination/rate-limiting natively — prefer over raw HTTP for GitHub
- Schema v16: 8 tables, inline `_synced_*` columns (no shadow tables) for diff/revert

## Linear

Project: **cass** — Team: **Ejolly** (EJO)

```bash
linear list-issues --project "cass"
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2
linear save-issue --id EJO-321 --state "In Progress"
```
