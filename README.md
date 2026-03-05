# cass

CLI grading toolkit for [GitHub Classroom](https://classroom.github.com/) and [Canvas LMS](https://www.instructure.com/canvas) — track submissions, deadlines, and sync grades.

Configure whichever systems your course uses: GitHub Classroom only, Canvas only, or both for combined roster matching and grade sync.

## Install

```bash
# Install as a CLI tool
uv tool install cass

# Or run directly without installing
uvx cass
```

Requires [`uv`](https://docs.astral.sh/uv/). Also requires the [GitHub CLI](https://cli.github.com/) (`gh`) if using GitHub Classroom.

## Quick start

```bash
# 1. Scaffold config and check setup
cass init

# 2. Pull everything from APIs into the local database
cass pull

# 3. View your data
cass students
cass assignments
cass submissions hw-01
cass grades
```

Running `cass` with no arguments shows a project status dashboard.

## Configuration

Create a `cass.toml` in your project root (or let `cass init` guide you). At least one section is required:

```toml
# GitHub Classroom
[classroom]
id = 299058
org = "psyc-201"

# Canvas LMS
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335
```

For Canvas, provide your API token via a `canvas-token.txt` file in the project root or the `CANVAS_TOKEN` environment variable.

## Commands

### Pull data

```bash
cass pull                     # fetch everything: students → assignments → submissions → grades
cass pull --students          # pull students only
cass pull --assignments       # pull assignments only
cass pull --submissions       # pull submissions only
cass pull --grades            # compute grades from submissions
cass pull --fetch             # also download student files
cass pull --limit 5           # limit students processed
```

### View data

```bash
cass students                 # student roster
cass students --all           # include excluded students
cass assignments              # assignment metadata
cass submissions              # all submissions
cass submissions hw-01        # filter by assignment slug
cass grades                   # gradebook matrix (students x assignments)
```

All view commands support:
- `--save <file.md>` — write output as markdown
- `--csv <file.csv>` — export as CSV
- `--where "expr"` — SQL WHERE clause filter

### Grade sync

```bash
cass grades push              # dry-run: preview what would be pushed to Canvas
cass grades push --post       # actually push grades
```

### File downloads

```bash
cass fetch hw-01              # download student files for an assignment
cass fetch all --force        # re-download everything
```

### Database tools

```bash
cass query "SELECT * FROM students WHERE canvas_id != ''"
cass query                    # interactive DuckDB REPL
cass view                     # open cass.db in Dataflare (GUI viewer)
```

[Dataflare](https://dataflare.app/) is a recommended GUI for browsing and editing the database interactively. Install with `brew install --cask dataflare`.

### Global flags

- `--no-cache` — bypass API cache
- `--ttl N` — cache TTL in hours (default: 6)
- `-V` / `--version` — show version

## How it works

All data lives in a local [DuckDB](https://duckdb.org/) database (`cass.db`) — no external database setup needed.

```
cass init    → creates cass.toml
cass pull    → fetches APIs → populates DuckDB
cass grades  → reads from DB → renders Rich tables
cass query   → direct SQL access for custom analysis
```

### Grading logic

**GitHub submissions** (binary: did you submit on time?)

| Condition | Grade | Numeric |
|-----------|-------|---------|
| No repo | `0` | 0 |
| Late | `0 (+1d 02:00)` | 0 |
| On time, no commits after deadline | `1` | 1 |
| On time, N commits after deadline | `1+ (N)` | 1 |

**Canvas submissions** (scored by the LMS)

| Condition | Grade | Numeric |
|-----------|-------|---------|
| Not submitted | `-` | — |
| Submitted, not graded | `?` | — |
| Graded | `42/50` | 42 |

## Development

```bash
uv sync                       # install all dependencies
uv run poe lint               # format + lint + type check
uv run poe test               # run test suite
```

## License

MIT
