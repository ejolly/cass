# Commitments

The authoritative list of non-negotiable project agreements. Each commitment states **what must hold** and **why**; scope, exceptions, and checks are optional. Adding, removing, or materially changing a commitment requires explicit human approval.

Number commitments C1, C2, etc. Never reuse a retired ID. Give each one a `##` heading ending in a stable anchor, such as `{#c1}`, so links like `commitments.md#c1` survive rewording the title. See the coherence skill's `references/commitments.md` for boundaries and agent behavior.

## C3. Quizzes behave on Canvas as their quiz file declares {#c3}

A quiz cass creates or updates must have, on Canvas, exactly the questions,
answers, correct answers, points, question groups, and settings its quiz file
declares. Students take a quiz once, under time pressure, so a quiz that
misbehaves cannot be fixed after the fact.

Check: `tests/live/test_live_quizzes.py`

## C4. Pulled grades and responses are complete, or say what is missing {#c4}

A pull of grades or a download of quiz responses must include every enrolled
student's current grades and finished attempts, or tell the user exactly what it
left out. Grading decisions made from silently incomplete or mismatched data are
wrong in ways no one notices.

## C5. Nothing becomes visible to students unless the user asked {#c5}

cass must never publish content or make it visible to students unless the user
explicitly asked for that, because students act on what they can see.
