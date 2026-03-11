# CLAUDE.md — cass

CLI grading toolkit for GitHub Classroom and Canvas LMS. TypeScript + Bun runtime. SQLite storage. NiceGUI browser viewer (Python, separate).

## Architecture

CLI (`src/cli/`) is a thin interface over a shared functional core.
**Never** put business logic, data transforms, queries, or API calls in CLI code.
Always use existing models (`db/schema.ts`, `apis/*/schema.ts`), operations (`db/`, `apis/`, `actions/`), and catalog metadata (`db/catalog.ts`). No ad-hoc objects, raw SQL in interfaces, or one-off data wrangling — if it doesn't exist in core, add it there first.

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
bun run typecheck          # tsc --noEmit (strict)
bun test                   # bun:test
bun run dev                # run CLI in dev mode
bun run build              # compile to dist/cassa
```

**Always run `bun run lint && bun run typecheck && bun test` before finishing work.**

Binary name: `cassa` (avoids conflict with Python `cass`).

## Style

- Zod schemas for API response types; TypeScript interfaces for internal types
- API types: `Canvas`/`GH`-prefixed Zod schemas. Domain types: unprefixed Kysely interfaces
- Error handling: `process.exit(1)` (fatal), `throw Error` (logic), `consola.error` (display)
- Biome for formatting + linting (2-space indent, 100 char line width)
- `ts-pattern` `.exhaustive()` for discriminated union dispatch
- Kysely typed query builder for all DB operations — no raw SQL
- Lazy dynamic imports where beneficial for startup performance

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
- GitHub Classroom URL `url_id` is the org ID, NOT the classroom API `gh_id` — cannot lookup by `url_id` directly
- `gh api --paginate` handles auth/pagination/rate-limiting natively — prefer over raw HTTP for GitHub
- Schema v16: 8 tables, inline `_synced_*` columns (no shadow tables) for diff/revert

## Linear

Project: **cass** — Team: **Ejolly** (EJO)

```bash
linear list-issues --project "cass"
linear save-issue --title "Title" --team "Ejolly" --project "cass" --priority 2
linear save-issue --id EJO-321 --state "In Progress"
```
