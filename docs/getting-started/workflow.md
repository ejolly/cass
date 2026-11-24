# Daily workflow

## Pull

```bash
cass pull
```

Fetches students, assignments, submissions, and grades from Canvas into `cass.db`. Grades are pulled as entered, before late deductions: points, a percentage, a letter, or complete/incomplete. cass blocks a pull while you have unpushed edits; push or revert first.

If `cass.db` comes from a version that did not pull grades, the first pull keeps each local grade that differs from Canvas, names it, and leaves it pending as a conflict. Push it to overwrite Canvas, or revert it and pull again to take the Canvas grade.

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

Three kinds of change are held back unless you approve them, and stay pending until you do:

- **Conflicts:** values that changed on Canvas since your last pull, for example a grade a TA entered in SpeedGrader. A grade cass has no last pulled value for also counts. Pushing would overwrite them.
- **Grades above points possible:** usually a typo, sometimes extra credit.
- **Cleared grades:** a grade you deleted in a cell. Pushing it removes the grade on Canvas.

`cass push` asks about each kind. With `--yes` there is no prompt, so pass `--overwrite-conflicts`, `--allow-over-points` or `--allow-clears` to include them. Two kinds are always held back: changes cass could not compare with Canvas, and grades Canvas would not record as entered. Canvas removes or replaces a grade it cannot read, so a grade must fit the assignment's grading type:

| Grading type | Grades cass pushes |
|---|---|
| Points | `9.5`, or `95%` |
| Percentage | `95%` |
| Letter or GPA, scheme set on the assignment or course | a letter in the scheme, `95%`, or points such as `9.5`, unless the scheme has an entry with that number as its name |
| Letter or GPA, no scheme set | `95%` |
| Complete/incomplete | `complete`, `incomplete`, `pass`, `fail` |

Percentages and letters are also held back when the assignment has no points possible, because Canvas records them as 0. On a complete/incomplete assignment with no points possible, Canvas ignores a change from one result to the other, so cass holds that back too: clear the grade and push, then enter the new one. Points possible come from Canvas at push time, plus any pending edit to them.

Sends every pending change to Canvas. The viewer's **Push** button does the same.

## Revert

```bash
cass revert
```

Discards all pending local edits and restores the last pulled values. A grade with no last pulled value is removed until the next pull.

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
