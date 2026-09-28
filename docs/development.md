# Development

```bash
git clone https://github.com/ejolly/cass.git && cd cass
uv sync --all-groups        # runtime, dev, and docs dependencies
uv run poe ok               # format, lint, type check, test
uv run poe ci               # the same gate without modifying files (what CI runs)
uv run poe docs-serve       # preview this site at localhost:8000
uv run poe install          # install your checkout as the global `cass`
```

## Layout

```
cass/cli/      Typer commands (thin)
cass/viewer/   NiceGUI browser UI (thin)
cass/actions/  orchestration: config, pull, doctor
cass/apis/     Canvas client and msgspec schemas
cass/db/       SQLite schema, CRUD, queries, sync, catalog
tests/         mirrors the source tree
```

CLI and viewer never contain business logic. They call `actions/`, which calls `db/` and `apis/`.

## Commits

Every commit subject follows [Conventional Commits](https://www.conventionalcommits.org): `type(scope): description`, with `type` one of `feat fix docs refactor perf test build ci chore style`. CI checks pull requests with `cz check`. git-cliff derives the changelog and version bumps from these subjects.

## Releasing

You cut releases locally; GitHub Actions publishes them.

```bash
uv run poe release              # version from commit types since the last tag
uv run poe release minor        # force a bump level: patch | minor | major
uv run poe release 1.0.0        # explicit version
uv run poe release --dry-run    # show what would happen
```

The script runs the gate, bumps `pyproject.toml`, regenerates `CHANGELOG.md`, commits `chore(release): vX.Y.Z`, tags, and pushes after you confirm. The tag triggers `.github/workflows/release.yml`, which builds, publishes to PyPI via trusted publishing, and creates a GitHub Release with the notes for that version.

## Test data

Tests that need real course data use the `real_db` fixture, which reads `tests/testdb/cass.db`. That snapshot is gitignored; regenerate it with `uv run poe seed-testdb` against the practice course. Without it those tests skip, which is what happens in CI.

## Live Canvas tests

Unit tests mock Canvas. Live tests in `tests/live/` call the real API to catch what mocks cannot: undocumented response shapes, report formats, redirects, and permissions. They run locally only, because CI has no Canvas credentials.

```bash
uv run poe live                              # seed the practice course, run live tests
CASS_LIVE_REAL_COURSE=<id> uv run poe live   # also run read-only real-course tests
uv run poe seed-live                         # seed only
```

- Credentials come from `.canvastoken` or `.canvascreds` in the repository root. Without them, live tests skip.
- `uv run poe test`, `ok`, and `ci` deselect the `live` marker.
- The `practice` fixture targets the course in `tests/live/cass.toml`, and tests may change its content. `seed-live` idempotently creates the quizzes declared there and submits them as the course's Test Student.
- The `real_course` fixture is read-only. It must not change content or grades, though generating quiz reports is fine. Its assertions check structure, never student data.
- Canvas leaves the Test Student out of quiz reports and statistics, so anything that reads student responses needs `real_course`.

### Pull requests written without Canvas access

When a change touches the Canvas API and was written somewhere without credentials, such as a cloud agent session:

1. Add live tests under `tests/live/` next to the mocked ones, even though you cannot run them.
2. Apply the `needs-live-check` label. In the pull request's "Live verification" section, list what the mocks assume.
3. Before merging, check out the branch locally, run `uv run poe live`, fix what it finds, and remove the label.
