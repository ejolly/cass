# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas) — pull rosters, track submissions, edit grades, and push them back to Canvas.

All data lives in a local SQLite database (`cass.db`) alongside a version-trackable `cass.toml` config.

## Install

```bash
uv tool install cassroom
```

## Quick start

```bash
cass init    # one-time setup: Canvas URL, course, credentials
cass pull    # fetch students, assignments, submissions
cass view    # edit grades in a browser grid
cass push    # send changes back to Canvas
```

## Documentation

Full guide, CLI reference, and API docs: **https://eshinjolly.com/cass**

## Development

```bash
uv sync --all-groups
uv run poe ok
```

See the [development guide](https://eshinjolly.com/cass/development/) for layout, commit conventions, and releasing.
