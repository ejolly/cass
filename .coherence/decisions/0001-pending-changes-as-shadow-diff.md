# 0001. Pending changes are a diff against the last pull

Status: Accepted

Date: 2026-03-06

## Context
Grade and assignment edits made in the viewer were held in memory, so they were
lost when the viewer restarted and were invisible to the CLI.

## Decision
After each pull, cass copies what Canvas has into shadow tables
(`_canvas_assignments_synced`, `_canvas_grades_synced`). A
[pending change](../domain.md#pending-change) is any difference between the
working tables and those shadows, computed with SQL.

## Rationale and trade-offs
Pending changes survive restarts and look the same from the viewer and from
`cass status`, and the shadow values give push a baseline to detect conflicts
with live Canvas. Costs were not recorded. Source: commit `731b802`.

## Alternatives
Holding edits in memory, the approach this replaced.
