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
