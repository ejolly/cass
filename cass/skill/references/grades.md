# Grades

## Pull

`cass pull` stores students, assignments, submissions and grades in `cass.db`. A grade is stored as entered, before late deductions. `score` in `cass query submissions` is Canvas's score, after them.

- Pull exits 1 while there are pending edits. Push or revert first. An edit saved during a pull stops the pull.
- The roster is every student with an active or invited enrollment. Pull deletes local students and assignments Canvas no longer lists, with their submissions and grades, and names each one. If Canvas lists none at all, as a concluded course may, pull keeps the local ones and says so. With no assignments listed, it refreshes no submissions or grades.
- A `cass.db` from a version that didn't pull grades has no record of what Canvas held. Until a full pull in which Canvas returns both students and assignments makes one, pull names and keeps each local grade that differs, and each one Canvas lists no grade for, along with its student and assignment. The full pull leaves them pending, which blocks further pulls. Where Canvas lists the student's submission, graded or not, the grade is a conflict: push it with `--overwrite-conflicts` or revert it. Where Canvas lists nothing, push can't send it; only revert clears it.
- `cass revert` drops every pending edit. A grade with no last pulled value is deleted: the next pull brings back Canvas's grade, if it lists one, never the local one. If Canvas lists none, the grade is lost, so have the user record it or run `cass backup` first.

## Push

`cass push` sends pending grades and pending assignment edits (name, points, due date, published). `--dry-run` compares them with live Canvas and prints a table, not requests. Each flag approves every row of its kind, and a row of two kinds needs both flags. `--yes` approves none of them.

| Held back | To send it |
|---|---|
| Changed on Canvas since the last pull, or a grade with no last pulled value (baseline `unknown`) | `--overwrite-conflicts` |
| Grade above points possible | `--allow-over-points` |
| Cleared grade (blank, `-` or `?`), which removes the grade on Canvas | `--allow-clears` |
| Grade the assignment doesn't take (next table) | no flag; the user corrects it |
| Could not be compared with Canvas, such as a student with no submission there, or edited after the preview | no flag |
| Points of a quiz with finished or uncheckable attempts | no flag; the user changes them in the Canvas web app |

| Grading type | Grades cass pushes |
|---|---|
| Points | `9.5`, or `95%` |
| Percentage | `95%`, never a plain number |
| Letter or GPA, scheme visible on the assignment or course | a letter in the scheme, `95%`, or points, unless an entry in the scheme has that number as its name |
| Letter or GPA, no scheme visible | `95%` |
| Complete/incomplete | `complete`, `incomplete`, `pass`, `fail` |

With 0 points possible, percentages and letters are held back, and so is a change between complete and incomplete: the user can clear the grade, push that, then enter the new one. A grade must fit the live points and any pending points edit.

- Held-back changes stay pending and the rest is sent. Push exits 1 if it held anything back or any Canvas update failed; a dry run exits 0. Failed updates print `✗` on stderr and stay pending. A failed update may be partly applied, for example when waiting for Canvas timed out or when Canvas kept an assignment's points but took its other fields, so check Canvas before retrying.
- cass rechecks quiz attempts just before sending points. A refusal then is a failed update.

## Release to students

On an assignment that posts grades automatically, pushing a grade shows it to the student. On one that posts manually, a pushed grade stays hidden until it is released. cass reads the posting policy from Canvas at the preview and again just before pushing.

- Without `--post`, `--yes` releases nothing. The dry run says how many grades would be pushed but not released, and the push says so again.
- `--post` prints how many grades it will release before pushing. It releases the grades this push sends, only for the students pushed, never cleared or held-back ones. Pass it only when the user asked to release them. It covers every manual-post assignment in the push, including one that started posting manually after the preview.
- `--post` releases only grades it pushes. A grade pushed without it must be released in the Canvas gradebook.
- A student whose grade was released before sees a change or a clear as soon as it is pushed, with or without `--post`. The preview counts these apart; tell the user before pushing. If cass can't tell whether a grade is released, it says so.
- When it pushes grades to a manual-post assignment, cass reads them back, with or without `--post`, and releases only those Canvas shows as pushed. A grade or clear Canvas ignored, or that someone else has changed, is not released and stays pending: push prints `✗` with the students' names and exits 1. The user checks them in Canvas, then pushes again or reverts. A grade Canvas now shows differently from the last pull is a conflict. If cass can't read the grades back, it releases none, and they are no longer pending. Pushes that only clear grades, and assignments that post automatically, are not read back. cass can't tell when someone else enters the same letter during a push, and can't prevent a change between reading the grades back and releasing them.
- If an assignment stops posting manually after the preview, push without release approval sends it nothing, because that would release the grades. The same applies if the approval did not count every grade in it, because cass could not tell which were released. If it starts posting manually, its grades are pushed but not released. If cass can't read the policy, nothing is sent for that assignment. A policy that changes in the moment between cass's last read and the push can't be caught.
- A release that fails prints `✗` and exits 1; the grades Canvas shows as pushed are no longer pending, and may not be released. Tell the user to check and post them in the Canvas gradebook.
