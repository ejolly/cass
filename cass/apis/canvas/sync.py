"""Canvas sync primitives — push grades and assignments to Canvas LMS.

Shared by both the CLI (``cass gradebook push``) and the NiceGUI viewer.
"""

from __future__ import annotations

__docformat__ = "google"

import json
import re
from collections.abc import Iterable
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
    "build_push_preview",
    "get_post_manually_map",
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


def get_post_manually_map(conn: sqlite_utils.Database) -> dict[int, bool]:
    """Load ``{canvas_assignment_id: post_manually}`` from DB."""
    rows = conn.execute(
        "SELECT canvas_id, post_manually FROM canvas_assignments"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def build_push_preview(
    conn: sqlite_utils.Database,
    grade_data_by_aid: dict[int, dict[int, str]],
    grades: list[CanvasGrade],
) -> list[dict[str, object]]:
    """Build a preview summary per assignment for push display.

    Returns:
        List of dicts with ``name``, ``canvas_id``, ``count``, ``post_manually``.
    """
    # Get assignment names
    rows = conn.execute("SELECT canvas_id, name FROM canvas_assignments").fetchall()
    aid_to_name: dict[int, str] = {r[0]: r[1] for r in rows}

    post_manually_map = get_post_manually_map(conn)

    # Collect all unique assignment IDs from grades
    all_aids = sorted({g.canvas_assignment_id for g in grades})

    preview: list[dict[str, object]] = []
    for aid in all_aids:
        pushable_count = len(grade_data_by_aid.get(aid, {}))
        preview.append(
            {
                "name": aid_to_name.get(aid, f"Assignment {aid}"),
                "canvas_id": aid,
                "count": pushable_count,
                "post_manually": bool(post_manually_map.get(aid)),
            }
        )
    return preview


# ---------------------------------------------------------------------------
# Core push functions
# ---------------------------------------------------------------------------


def push_grades(
    client: CanvasClient,
    conn: sqlite_utils.Database,
    grade_data_by_aid: dict[int, dict[int, str]],
) -> list[dict[str, object]]:
    """Bulk-push grades to Canvas, handling progress tracking and post_manually.

    Args:
        client: Authenticated Canvas API client.
        conn: SQLite database connection (for post_manually lookup).
        grade_data_by_aid: ``{assignment_id: {user_id: grade_string}}``.

    Returns:
        List of result dicts with ``ok``, ``canvas_assignment_id``, ``count``,
        and optionally ``error`` or ``action`` keys.
    """
    results: list[dict[str, object]] = []
    if not grade_data_by_aid:
        return results

    post_manually_map = get_post_manually_map(conn)

    pushed_aids: list[int] = []
    for aid, grade_data in grade_data_by_aid.items():
        try:
            progress = client.bulk_push_grades(aid, grade_data)
            client.wait_for_progress(progress.id)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": True,
                    "count": len(grade_data),
                }
            )
            pushed_aids.append(aid)
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "error": str(e),
                    "count": len(grade_data),
                }
            )

    # Post grades for manual-post assignments (make visible to students)
    for aid in pushed_aids:
        if not post_manually_map.get(aid):
            continue
        try:
            p = client.post_assignment_grades(aid, graded_only=True)
            if p:
                client.wait_for_progress(p.id)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": True,
                    "action": "posted_to_students",
                }
            )
        except Exception as e:
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "action": "posted_to_students",
                    "error": str(e),
                }
            )

    return results


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
                _require_points_kept(updated, kwargs["points_possible"])
            results.append({"canvas_id": canvas_id, "ok": True})
        except Exception as e:
            results.append({"canvas_id": canvas_id, "ok": False, "error": str(e)})
    return results


def _require_points_kept(updated: CanvasAssignmentResponse, sent: object) -> None:
    """Raise if Canvas kept other points, as it does on a published quiz."""
    sent_points = float(cast(float | str | None, sent) or 0)
    if (updated.points_possible or 0.0) != sent_points:
        raise RuntimeError(f"Canvas kept points_possible at {updated.points_possible}")
