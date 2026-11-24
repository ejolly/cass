"""Canvas sync primitives — push grades and assignments to Canvas LMS.

Shared by both the CLI (``cass gradebook push``) and the NiceGUI viewer.
"""

from __future__ import annotations

__docformat__ = "google"

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING, cast

import sqlite_utils

from .attempts import refuse_if_assignment_attempted
from .times import same_instant

if TYPE_CHECKING:
    from ...db.schema import CanvasGrade
    from .client import CanvasClient
    from .schema import CanvasAssignmentResponse

__all__ = [
    "accepts_grade",
    "build_grade_push_data",
    "get_post_manually",
    "get_scheme_letters",
    "is_valid_grade",
    "pass_fail_change_ignored",
    "push_assignments",
    "push_grades",
    "resolve_group_ids",
    "resolve_row_name",
    "same_instant",
    "values_equal",
]


def values_equal(a: object, b: object) -> bool:
    """Compare values loosely, handling datetime/string equivalence."""
    if a == b:
        return True
    if isinstance(a, (datetime, date)) and isinstance(b, str):
        return a.isoformat() == b or str(a) == b
    if isinstance(b, (datetime, date)) and isinstance(a, str):
        return b.isoformat() == a or str(b) == a
    return False


def resolve_row_name(
    conn: sqlite_utils.Database,
    table: str,
    pk_key: str,
) -> str:
    """Resolve a pending-change pk_key to a human-readable row name."""
    if table == "canvas_assignments":
        row = conn.execute(
            "SELECT name FROM canvas_assignments WHERE canvas_id = ?",
            [int(pk_key)],
        ).fetchone()
        return row[0] if row else pk_key
    if table == "canvas_grades":
        pk = json.loads(pk_key)
        uid, aid = pk["canvas_user_id"], pk["canvas_assignment_id"]
        row = conn.execute(
            "SELECT st.name, ca.name "
            "FROM canvas_students st, canvas_assignments ca "
            "WHERE st.canvas_id = ? AND ca.canvas_id = ?",
            [uid, aid],
        ).fetchone()
        if row:
            return f"{row[0]} — {row[1]}"
        return pk_key
    return pk_key


# ---------------------------------------------------------------------------
# Grade data helpers
# ---------------------------------------------------------------------------


def is_valid_grade(grade: str | None) -> bool:
    """Return True if grade is non-empty and not a placeholder."""
    return bool(grade) and grade.strip() not in ("", "-", "?")


_NUMBER = r"[+-]?([0-9]+(\.[0-9]+)?|\.[0-9]+)"
_LETTER_GRADING_TYPES = ("letter_grade", "gpa_scale")
# Words Canvas reads as full or no credit, whatever the grading type.
_PASS_FAIL_GRADES = frozenset({"complete", "incomplete", "pass", "fail"})


def get_scheme_letters(
    client: CanvasClient, assignment: CanvasAssignmentResponse
) -> frozenset[str]:
    """Return the names in the letter scheme set on the assignment or the course.

    Empty when no scheme is visible: neither sets one, Canvas does not list the
    one set, or it is 0. Canvas may then use an account's default scheme, which
    cass cannot read. Also empty for grading types that take no letters.
    """
    if assignment.grading_type not in _LETTER_GRADING_TYPES:
        return frozenset()
    standard_id = assignment.grading_standard_id
    if standard_id is None:
        standard_id = client.get_course().grading_standard_id
    if not standard_id:
        return frozenset()
    for standard in client.list_grading_standards():
        if standard.id == standard_id:
            return frozenset(entry.name for entry in standard.grading_scheme)
    return frozenset()


def accepts_grade(
    grade: str,
    grading_type: str,
    letters: frozenset[str],
    points_possible: float | None,
) -> bool:
    """Return whether Canvas records this grade as entered.

    Canvas does not reject other text: it removes the student's grade or turns
    it into a different one (checked in ``tests/live/test_live_grade_input.py``).
    Percentages and letters are worth a share of the points possible, so
    without points Canvas records them as 0.

    Args:
        grade: The grade to push.
        grading_type: The assignment's live grading type.
        letters: Names in the visible scheme, from ``get_scheme_letters``.
        points_possible: The assignment's points possible.
    """
    text = grade.strip()
    is_number = re.fullmatch(_NUMBER, text) is not None
    if re.fullmatch(_NUMBER + "%", text):
        takes_percent = grading_type in ("points", "percent", *_LETTER_GRADING_TYPES)
        return takes_percent and bool(points_possible)
    if grading_type == "points":
        return is_number
    if grading_type == "percent":
        # A plain number would be read as points: 95 out of 10 becomes 950%.
        return False
    if grading_type == "pass_fail":
        return text in _PASS_FAIL_GRADES
    if grading_type not in _LETTER_GRADING_TYPES or text in _PASS_FAIL_GRADES:
        return False
    if is_number:
        # Canvas looks a number up in the scheme before reading it as points.
        return bool(letters) and float(text) not in _scheme_numbers(letters)
    return bool(points_possible) and (text in letters or text.upper() in letters)


def pass_fail_change_ignored(
    grade: str,
    live_grade: str | None,
    grading_type: str,
    points_possible: float | None,
) -> bool:
    """Return whether Canvas would ignore a change of a complete/incomplete grade.

    Without points possible, both results score 0, and Canvas keeps the existing
    grade when the score does not change.
    """
    if grading_type != "pass_fail" or points_possible:
        return False
    if not is_valid_grade(live_grade):
        return False
    same_result = {"pass": "complete", "fail": "incomplete"}
    new = grade.strip()
    return same_result.get(new, new) != same_result.get(live_grade, live_grade)


def _scheme_numbers(letters: frozenset[str]) -> set[float]:
    """Return the scheme names that are numbers, as in a 4/3/2/1 scheme."""
    return {float(name) for name in letters if re.fullmatch(_NUMBER, name.strip())}


def build_grade_push_data(
    grades: list[CanvasGrade],
) -> tuple[dict[int, dict[int, str]], int]:
    """Build ``{aid: {uid: grade}}`` from CanvasGrade list, filtering placeholders.

    Returns:
        Tuple of (grade_data_by_aid, skipped_count).
    """
    grade_data_by_aid: dict[int, dict[int, str]] = {}
    skipped = 0
    for g in grades:
        if not is_valid_grade(g.posted_grade):
            skipped += 1
            continue
        grade_data_by_aid.setdefault(g.canvas_assignment_id, {})[g.canvas_user_id] = (
            g.posted_grade
        )
    return grade_data_by_aid, skipped


def get_post_manually(assignment: CanvasAssignmentResponse) -> bool:
    """Return whether a live assignment has a manual posting policy.

    Raises:
        RuntimeError: If Canvas did not say. A grade pushed to an assignment
            that posts automatically is visible to students at once, so the
            policy must not be guessed.
    """
    if assignment.post_manually is None:
        raise RuntimeError("Canvas did not return the assignment's posting policy")
    return assignment.post_manually


# ---------------------------------------------------------------------------
# Core push functions
# ---------------------------------------------------------------------------


def push_grades(
    client: CanvasClient,
    conn: sqlite_utils.Database,
    grade_data_by_aid: dict[int, dict[int, str]],
    *,
    post_grades: bool = False,
    previewed_policies: Mapping[int, bool] | None = None,
) -> list[dict[str, object]]:
    """Bulk-push grades to Canvas, releasing them to students only if approved.

    On an assignment that posts automatically, the push itself releases grades.
    On one that posts manually, the pushed grades of students who got one are
    released only with ``post_grades`` (commitment C5). The posting policy is
    read live just before each push.

    ``previewed_policies`` limits ``post_grades`` to assignments that posted
    manually when the user approved. It also fails, without sending it, an
    assignment that has since started posting automatically if its release was
    not approved.

    Args:
        client: Authenticated Canvas API client.
        conn: SQLite database connection. The stored posting policy is not used.
        grade_data_by_aid: ``{assignment_id: {user_id: grade_string}}``. An
            empty grade removes the grade on Canvas and is never released.
        post_grades: The user approved releasing the pushed grades.
        previewed_policies: ``post_manually`` by assignment, as the user saw it.
            None means the approval covers whatever the policy is now.

    Returns:
        List of result dicts with ``ok`` and ``canvas_assignment_id``. A push
        also has ``count``, and ``unreleased`` (grades pushed without trying to
        release them) if it succeeded; a release has the ``action``
        ``posted_to_students``. Failures have an ``error``.
    """
    results: list[dict[str, object]] = []
    for aid, grade_data in grade_data_by_aid.items():
        release_approved = post_grades and (
            previewed_policies is None or previewed_policies.get(aid) is True
        )
        previewed_automatic = (
            previewed_policies is None or previewed_policies.get(aid) is False
        )
        try:
            post_manually = get_post_manually(client.get_assignment(aid))
            if not (post_manually or release_approved or previewed_automatic):
                raise RuntimeError(
                    "grades now post automatically on this assignment, so pushing "
                    "would release them to students without approval; "
                    "nothing was sent. Push again to review it."
                )
            progress = client.bulk_push_grades(aid, grade_data)
            client.wait_for_progress(progress.id)
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "error": str(e),
                    "count": len(grade_data),
                }
            )
            continue

        graded_ids = [uid for uid, grade in grade_data.items() if is_valid_grade(grade)]
        release = post_manually and release_approved
        results.append(
            {
                "canvas_assignment_id": aid,
                "ok": True,
                "count": len(grade_data),
                "unreleased": len(graded_ids) if post_manually and not release else 0,
            }
        )
        if release and graded_ids:
            results.append(_release_grades(client, aid, graded_ids))
    return results


def _release_grades(
    client: CanvasClient, assignment_id: int, student_ids: list[int]
) -> dict[str, object]:
    """Post these students' pushed grades; returns a push result row."""
    result: dict[str, object] = {
        "canvas_assignment_id": assignment_id,
        "action": "posted_to_students",
    }
    try:
        progress = client.post_assignment_grades(
            assignment_id, graded_only=True, only_student_ids=student_ids
        )
        if progress is None:
            raise RuntimeError("Canvas did not start posting")
        client.wait_for_progress(progress.id)
    except Exception as e:
        error = (
            f"{len(student_ids)} grade(s) pushed but not released to students: "
            f"{e}. Check the Canvas gradebook and post them there."
        )
        return {**result, "ok": False, "error": error}
    return {**result, "ok": True}


def resolve_group_ids(
    client: CanvasClient, names: Iterable[str]
) -> tuple[dict[str, int], list[str]]:
    """Map assignment group names to IDs, case-insensitively.

    Returns:
        ``(ids keyed by lower-cased name, names with no live match)``. A
        missing name is listed once, as first spelled.
    """
    live = {g.name.lower(): g.id for g in client.list_assignment_groups()}
    ids: dict[str, int] = {}
    missing: list[str] = []
    for name in names:
        key = name.lower()
        if key in live:
            ids[key] = live[key]
        elif key not in {m.lower() for m in missing}:
            missing.append(name)
    return ids, missing


def push_assignments(
    client: CanvasClient,
    updates_by_id: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    """Push assignment field updates to Canvas.

    Before sending a points change, checks that the assignment is not a quiz
    students have finished (commitment C2). A refused assignment is not updated
    and gets a failed result, as does one whose new points Canvas did not keep.
    In that case Canvas may have applied the other fields sent with the points,
    and the error names them.

    Args:
        client: Authenticated Canvas API client.
        updates_by_id: ``{canvas_assignment_id: {field: new_value}}``.

    Returns:
        List of result dicts with ``ok``, ``canvas_id``, and optionally ``error``.
    """
    results: list[dict[str, object]] = []
    for canvas_id, kwargs in updates_by_id.items():
        try:
            if "points_possible" in kwargs:
                refuse_if_assignment_attempted(
                    client, client.get_assignment(canvas_id), "change points_possible"
                )
            updated = client.update_assignment(canvas_id, **kwargs)
            if "points_possible" in kwargs:
                _require_points_kept(updated, kwargs)
            results.append({"canvas_id": canvas_id, "ok": True})
        except Exception as e:
            results.append({"canvas_id": canvas_id, "ok": False, "error": str(e)})
    return results


def _require_points_kept(
    updated: CanvasAssignmentResponse, sent: dict[str, object]
) -> None:
    """Raise if Canvas kept other points, as it does on a published quiz."""
    sent_points = float(cast(float | str | None, sent["points_possible"]) or 0)
    if (updated.points_possible or 0.0) == sent_points:
        return
    message = f"Canvas kept points_possible at {updated.points_possible}"
    other_fields = ", ".join(name for name in sent if name != "points_possible")
    if other_fields:
        message += f"; the other fields sent ({other_fields}) may have been applied"
    raise RuntimeError(message)
