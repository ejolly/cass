# 0005. Grades Canvas may not record as entered are held back

Status: Accepted

Date: 2026-11-23

## Context
Canvas does not reject a grade it cannot read. It can remove the student's
existing grade or record a different one, and still report that the update
completed. On the practice course, pushing `B+` to a points assignment removed
the grade, and pushing `95` to a percent assignment recorded 950%.

## Decision
Before pushing, cass checks each grade against the assignment's live grading
type. It holds back a grade that Canvas may not record as entered, and no flag
overrides this. On a letter or GPA assignment, a letter must be in the grading
scheme set on the assignment or the course. If neither sets one, cass holds back
every letter. Points and percentages can still be pushed there, and Canvas shows
them as letters.

## Rationale and trade-offs
Without a scheme on the assignment or course, Canvas can use an account's
default scheme, which cass does not read. A letter missing from that scheme
could remove a grade ([C1](../commitments.md#c1)). The accepted cost is that the
user must set a scheme on the assignment or course, or enter the grade in
Canvas, before letters work there. A value cass wrongly refuses can be entered
in Canvas.

## Alternatives
Assuming Canvas's built-in letters when no scheme is visible, as cass first did.
It was rejected because the account's default scheme may differ.
