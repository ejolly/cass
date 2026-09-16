# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas). Pull your roster, assignments, and submissions into a local SQLite database, edit grades in a browser grid or from the terminal, and push the changes back to Canvas.

All data lives in `cass.db` next to a version-trackable `cass.toml` in your course directory.

## Quick start

```bash
uv tool install cassroom   # install
cass init                  # one-time: Canvas URL, course, credentials
cass pull                  # fetch students, assignments, submissions
cass view                  # open the grading grid in your browser
cass push                  # send edited grades to Canvas
```

## Where next

- [Install](getting-started/install.md) and [set up](getting-started/setup.md) a course directory.
- Learn the [daily workflow](getting-started/workflow.md): pull, edit, push, revert, back up.
- Use the [viewer](guide/viewer.md) or the [CLI](guide/cli.md).
- Browse the [CLI reference](reference/cli.md) and the [API reference](reference/api/actions.md).
