# Daily workflow

## Pull

```bash
cass pull
```

Fetches students, assignments, and submissions from Canvas into `cass.db`. cass blocks a pull while you have unpushed edits; push or revert first.

## Edit

Open the browser grid:

```bash
cass view
```

Double-click a cell in the **Gradebook** or **Assignments** table to edit it. Edited cells turn orange and persist across restarts until you push or revert. See [Viewer](../guide/viewer.md).

Or edit from the terminal with the `cass canvas` commands; see [CLI](../guide/cli.md).

## Push

```bash
cass push          # preview, then confirm
cass push --yes    # skip the confirmation
```

Sends every pending change to Canvas. The viewer's **Push** button does the same.

## Revert

```bash
cass revert
```

Discards all pending local edits and restores the last pulled values.

## Status

```bash
cass status
```

Shows local counts and pending changes. Running `cass` with no arguments prints the same overview plus a command summary.

## Back up and restore

```bash
cass backup                          # backups/cass_<timestamp>.db
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.db
```

Back up before bulk edits. Restore replaces `cass.db` with the snapshot.
