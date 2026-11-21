# Commitments

The authoritative list of non-negotiable project agreements. Each commitment states **what must hold** and **why**; scope, exceptions, and checks are optional. Adding, removing, or materially changing a commitment requires explicit human approval.

Number commitments C1, C2, etc. Never reuse a retired ID. Give each one a `##` heading ending in a stable anchor, such as `{#c1}`, so links like `commitments.md#c1` survive rewording the title. See the coherence skill's `references/commitments.md` for boundaries and agent behavior.

## C1. Grades on Canvas change only as the user approved {#c1}

cass must never clear, overwrite, or misattribute a [grade](domain.md#grade) on Canvas: every grade
it writes must be the exact value the user entered or approved, for the exact
student and assignment they entered it for. A grade above the assignment's
points possible must not be pushed unless the user confirmed it. A wrong or lost
grade harms a real student, and it may go unnoticed until after grades are final.

## C2. cass never deletes or alters a quiz that has student attempts {#c2}

cass must refuse to delete a [quiz](domain.md#quiz), or change its questions, answers, points, or
scoring settings, once any student has a [finished attempt](domain.md#finished-attempt), and tell the user to
make the change in the Canvas web app instead. Such changes can destroy or alter
student work, and Canvas's own interface handles their consequences, such as
regrading, which cass does not.

## C3. Quizzes behave on Canvas as their quiz file declares {#c3}

A [quiz](domain.md#quiz) cass creates or updates must have, on Canvas, exactly the questions,
answers, correct answers, points, question groups, and settings its quiz file
declares. Students take a quiz once, under time pressure, so a quiz that
misbehaves cannot be fixed after the fact.

Check: `tests/live/test_live_quizzes.py`

## C4. Pulled grades and responses are complete, or say what is missing {#c4}

A pull of grades or a download of quiz responses must include every enrolled
[student](domain.md#student)'s current grades and [finished attempts](domain.md#finished-attempt), or tell the user exactly what it
left out. Grading decisions made from silently incomplete or mismatched data are
wrong in ways no one notices.

## C5. Nothing becomes visible to students unless the user asked {#c5}

cass must never publish content or make it [visible to students](domain.md#visible-to-students) unless the user
explicitly asked for that, because students act on what they can see.

## C6. The CLI and viewer contain no business logic {#c6}

The CLI (`cass/cli/`) and viewer (`cass/viewer/`) must only call the shared core
(`cass/actions/`, `cass/apis/`, `cass/db/`). Business logic, data transforms,
database queries, and Canvas API calls must live in the core, so each rule cass
enforces, including every other commitment, holds the same in both interfaces.
