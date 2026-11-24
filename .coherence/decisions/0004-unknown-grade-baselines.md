# 0004. A grade with an unknown baseline is kept as a conflict

Status: Accepted

Date: 2026-11-23

## Context
Pull did not record the grades Canvas had, so in an existing `cass.db` a local
grade that differs from Canvas may be an edit that was never pushed, or an old
value that Canvas has since changed. cass cannot tell which.

## Decision
A grade whose Canvas value at the last pull is unknown has no row in the
`_canvas_grades_synced` shadow table of
[0001](0001-pending-changes-as-shadow-diff.md). If it is not blank, it is a
[pending change](../domain.md#pending-change) and always a conflict. The first
full pull after the upgrade keeps every differing local grade this way. A blank
one is not pending, and the next pull replaces it with Canvas's value.

## Rationale and trade-offs
No local grade is overwritten silently, and none replaces a grade on Canvas
without approval ([C1](../commitments.md#c1)). A blank is not pushed, because it
may be an absent value rather than a request to remove a grade. The accepted
costs are that a kept grade blocks the next pull until it is pushed or reverted,
and that clearing a kept grade takes effect only if it is repeated after the
next pull and pushed.

## Alternatives
Treating a blank with an unknown baseline as a pending clear, which would
propose removing a grade on Canvas that the user may not have meant to remove.
