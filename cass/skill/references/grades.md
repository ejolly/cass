# Grades

## Pull

`cass pull` stores students, assignments, submissions and grades in `cass.db`. A grade is stored as entered, before late deductions. `score` in `cass query submissions` is Canvas's score, after them.

- Pull exits 1 while there are pending edits. Push or revert first. An edit saved during a pull stops the pull.
- The roster is every student with an active or invited enrollment. Pull deletes local students and assignments Canvas no longer lists, with their submissions and grades, and names each one. If Canvas lists none at all, as a concluded course may, pull keeps the local ones and says so. With no assignments listed, it refreshes no submissions or grades.
- A `cass.db` from a version that didn't pull grades has no record of what Canvas held. Until a full pull makes one, pull names and keeps each local grade that differs, and each one Canvas lists no grade for, along with its student and assignment. They are left pending as conflicts: the user pushes or reverts them.
- `cass revert` drops every pending edit. A grade with no last pulled value disappears until the next pull.

## Push

`cass push` sends pending grades and pending assignment edits (name, points, due date, published). `--dry-run` compares them with live Canvas and prints a table, not requests. Each flag approves every row of its kind, and a row of two kinds needs both flags. `--yes` approves none of them.

| Held back | To send it |
|---|---|
| Changed on Canvas since the last pull, or a grade with no last pulled value | `--overwrite-conflicts` |
| Grade above points possible | `--allow-over-points` |
| Cleared grade, which removes the grade on Canvas | `--allow-clears` |
| Grade the assignment doesn't take (next table) | no flag; the user corrects it |
| Could not be compared with Canvas, such as a student with no submission there | no flag |
| Points of a quiz with finished or uncheckable attempts | no flag; the user changes them in the Canvas web app |

| Grading type | Grades cass pushes |
|---|---|
| Points | `9.5`, or `95%` |
| Percentage | `95%`, never a plain number |
| Letter or GPA, scheme visible on the assignment or course | a letter in the scheme, `95%`, or points, unless an entry in the scheme has that number as its name |
| Letter or GPA, no scheme visible | `95%` |
| Complete/incomplete | `complete`, `incomplete`, `pass`, `fail` |

With 0 points possible, percentages and letters are held back, and so is a change between complete and incomplete: the user can clear the grade, push that, then enter the new one. A grade must fit the live points and any pending points edit.

- Held-back changes stay pending and the rest is sent. Push exits 1 if it held anything back; a dry run exits 0. It exits 0 when only Canvas updates fail; those print `✗` on stderr and stay pending. When a post to students fails, the grades are already pushed.
- cass rechecks quiz attempts just before sending points. A refusal then is a failed update.
- **Manual posting:** after pushing grades to an assignment that posts manually (as of the last pull), cass posts every graded submission on it, not only the pushed ones. The dry run doesn't show this. Tell the user before pushing.
