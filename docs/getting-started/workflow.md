# Daily workflow

## Pull

```bash
cass pull
```

Fetches students, assignments, submissions, and grades from Canvas into `cass.db`. Grades are pulled as entered, before late deductions: points, a percentage, a letter, or complete/incomplete. cass blocks a pull while you have unpushed edits; push or revert first. An edit saved while a pull is running stops the pull.

Students no longer enrolled and assignments deleted on Canvas are removed from `cass.db`, along with their submissions and grades, and the pull names each one. If Canvas returns no students or no assignments at all, as it may for a concluded course, the pull keeps the local ones and says so. With no assignments listed, it does not refresh submissions and grades.

If `cass.db` comes from a version that did not pull grades, the first pull keeps each local grade that differs from Canvas, names it, and leaves it pending as a conflict. Push it, approving the conflict, to overwrite Canvas, or revert it and pull again to take the Canvas grade. A local grade Canvas lists nothing for, such as one of a departed student or on a deleted assignment, is also kept and left pending. Push can't send it; only reverting clears it, which deletes the grade, and the next pull removes the student or assignment. Record the grade or run `cass backup` first. This waits for a pull in which Canvas returns both students and assignments.

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
cass push --post   # also release the pushed grades to students
```

Three kinds of change are held back unless you approve them, and stay pending until you do:

- **Conflicts:** values that changed on Canvas since your last pull, for example a grade a TA entered in SpeedGrader. A grade cass has no last pulled value for also counts. Pushing would overwrite them.
- **Grades above points possible:** usually a typo, sometimes extra credit.
- **Cleared grades:** a grade you deleted in a cell. Pushing it removes the grade on Canvas.

`cass push` asks about each kind. With `--yes` there is no prompt, so pass `--overwrite-conflicts`, `--allow-over-points` or `--allow-clears` to include them. Three kinds are always held back: changes cass could not compare with Canvas, points of a quiz students have finished or whose attempts cass could not check (change them in the Canvas web app), and grades Canvas would not record as entered. Canvas removes or replaces a grade it cannot read, so a grade must fit the assignment's grading type:

| Grading type | Grades cass pushes |
|---|---|
| Points | `9.5`, or `95%` |
| Percentage | `95%` |
| Letter or GPA, scheme set on the assignment or course | a letter in the scheme, `95%`, or points such as `9.5`, unless the scheme has an entry with that number as its name |
| Letter or GPA, no scheme set | `95%` |
| Complete/incomplete | `complete`, `incomplete`, `pass`, `fail` |

Percentages and letters are also held back when the assignment has no points possible, because Canvas records them as 0. On a complete/incomplete assignment with no points possible, Canvas ignores a change from one result to the other, so cass holds that back too: clear the grade and push, then enter the new one. Points possible come from Canvas at push time, plus any pending edit to them.

Sends every other pending change to Canvas. The viewer's **Push** button does the same.

### Releasing grades to students

On an assignment that posts grades automatically, students see a grade as soon as you push it. On one that posts manually, pushed grades stay hidden until you release them. `cass push` asks whether to release the grades it is about to push, for those students only; the default is no. In the viewer, tick **Release N pushed grade(s) to students**. `--post` releases them without asking. `--yes` alone releases nothing, and `cass push --dry-run` shows how many grades would be pushed but not released.

- A grade you push without releasing is released later in the Canvas gradebook. `--post` covers only grades in the same push.
- Cleared and held-back grades are never released.
- A student whose grade was already released sees a changed or cleared grade as soon as you push it. cass counts these separately before you confirm, and says so if it can't tell whether a grade is released.
- After pushing, cass reads the grades back and releases only those Canvas shows as pushed. A grade that Canvas ignored or removed, or that someone else has changed, is not released, and `cass push` says how many and exits 1. If cass can't read the grades back, it releases none. cass can't tell when someone else enters the same letter during a push, and can't prevent a change between reading the grades back and releasing them.
- cass reads the posting policy from Canvas at the preview and again when it pushes. If an assignment started posting automatically in between and you did not approve releasing its grades, nothing is sent for it. If it started posting manually, its grades are pushed but not released, unless you passed `--post`. If the policy can't be read, nothing is sent. A policy that changes in the moment between the last read and the push can't be caught.
- If releasing fails, the grades are still pushed but may not be released. cass tells you to check them in Canvas and exits 1.

## Revert

```bash
cass revert
```

Discards all pending local edits and restores the last pulled values. A grade with no last pulled value is deleted: the next pull brings back Canvas's grade, if it lists one, never the local one. If Canvas lists none, the grade is lost, so record it or run `cass backup` first.

## Status

```bash
cass status
```

Shows local counts and pending changes. Running `cass` with no arguments prints the help.

## Back up and restore

```bash
cass backup                          # backups/cass_<timestamp>.db
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.db
```

Back up before bulk edits. Restore replaces `cass.db` with the snapshot.
