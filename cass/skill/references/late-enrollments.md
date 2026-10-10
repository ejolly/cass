# Late enrollments

Use these when a student joins after some work was due, to excuse that work or clear late penalties.

## Find them

```bash
cass canvas people list --enrolled-after 2026-10-01 --json
cass canvas people list --state completed --state inactive
```

- `enrolled at` is the earliest `created_at` across a person's enrollments, deleted ones included. A bare date means midnight in course time.
- `--enrolled-after` keeps people of any role. `--state` can be repeated, and it defaults to active and invited.

## Excuse or clear late

Both commands take exactly one of `--student ID` or `--enrolled-after DATE`. `--student` can be repeated and needs an ASSIGNMENT. Both are dry runs until you pass `--apply`.

```bash
cass canvas submissions excuse --enrolled-after 2026-10-01                  # plan across all assignments
cass canvas submissions excuse --enrolled-after 2026-10-01 --apply
cass canvas submissions excuse HW1 --student 123                            # one student, one assignment
cass canvas submissions excuse HW1 --student 123 --include-graded --apply
cass canvas submissions clear-late HW1 --student 123 --apply
cass canvas submissions list HW1 --student 123 --json                       # check the result
```

- `--enrolled-after` counts only `StudentEnrollment` students who are `active` or `invited`, never the Test Student. It picks a submission when the assignment was due, by the student's own due date, before the student enrolled. Assignments that are unpublished or have no due date are never touched. An unpublished ASSIGNMENT exits 1.
- `--student` with an explicit ASSIGNMENT acts even when the assignment is unpublished or undated, and warns.
- `excuse` skips graded submissions, because excusing clears the grade. `--include-graded` overrides this. Canvas's automatic missing-policy score is not protected. A submission someone marked Missing by hand in the gradebook is protected, and excusing it needs `--include-graded`. Submitted but ungraded work is excused.
- `clear-late` acts only on submissions marked `late`. It sets their late status to `none`, which clears the late flag and restores deducted points; the dry run shows the points. It skips submissions that aren't late (a missing-only submission included), excused submissions and group-graded assignments. Excuse a late enrollee's missing work with `excuse`; clear group-graded ones in Canvas.
- A late resubmission makes the submission late again, so run `clear-late` again. If the student resubmitted after grading, the deduction stays until the submission is regraded.
- Canvas fills in a new student's due dates a few moments after enrollment, so rerun the dry run if a just-added student is missing.
