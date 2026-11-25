"""Canvas sync primitives — push grades and assignments to Canvas LMS.

Shared by both the CLI (``cass gradebook push``) and the NiceGUI viewer.
"""

from __future__ import annotations

__docformat__ = "google"

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, cast

import msgspec
import sqlite_utils

from .attempts import refuse_if_assignment_attempted
from .times import same_instant

if TYPE_CHECKING:
    from ...db.schema import CanvasGrade
    from .client import CanvasClient
    from .schema import (
        CanvasAssignmentResponse,
        CanvasGradingSchemeEntry,
        CanvasSubmissionResponse,
    )

__all__ = [
    "PostingPreview",
    "accepts_grade",
    "build_grade_push_data",
    "get_post_manually",
    "get_scheme",
    "get_scheme_letters",
    "is_valid_grade",
    "pass_fail_change_ignored",
    "push_assignments",
    "push_grades",
    "resolve_group_ids",
    "resolve_row_name",
    "same_instant",
    "shows_pushed_grade",
    "student_name",
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


def student_name(conn: sqlite_utils.Database, user_id: int) -> str:
    """Return a student's name, or ``User <id>`` if not stored locally."""
    row = conn.execute(
        "SELECT name FROM canvas_students WHERE canvas_id = ?", [user_id]
    ).fetchone()
    return str(row[0]) if row else f"User {user_id}"


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


def get_scheme(
    client: CanvasClient, assignment: CanvasAssignmentResponse
) -> list[CanvasGradingSchemeEntry]:
    """Return the letter scheme set on the assignment or the course.

    Empty when no scheme is visible: neither sets one, Canvas does not list the
    one set, or it is 0. Canvas may then use an account's default scheme, which
    cass cannot read. Also empty for grading types that take no letters.
    """
    if assignment.grading_type not in _LETTER_GRADING_TYPES:
        return []
    standard_id = assignment.grading_standard_id
    if standard_id is None:
        standard_id = client.get_course().grading_standard_id
    if not standard_id:
        return []
    for standard in client.list_grading_standards():
        if standard.id == standard_id:
            return standard.grading_scheme
    return []


def get_scheme_letters(
    client: CanvasClient, assignment: CanvasAssignmentResponse
) -> frozenset[str]:
    """Return the names in the visible letter scheme (see ``get_scheme``)."""
    return frozenset(entry.name for entry in get_scheme(client, assignment))


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


def shows_pushed_grade(
    sent: str,
    submission: CanvasSubmissionResponse,
    grading_type: str,
    points_possible: float | None,
    scheme: list[CanvasGradingSchemeEntry],
) -> bool:
    """Return whether Canvas shows the grade that was sent as the entered grade.

    Allows for the forms Canvas gives a grade (checked in
    ``tests/live/test_live_grade_posting.py``): ``8.50`` becomes ``8.5``, ``95%``
    becomes points or a letter, and ``pass`` becomes ``complete``. Anything not
    recognized does not match.
    """
    sent = sent.strip()
    shown = (submission.entered_grade or "").strip()
    if not is_valid_grade(sent) or not is_valid_grade(shown):
        return False
    if grading_type == "pass_fail":
        return {"pass": "complete", "fail": "incomplete"}.get(sent, sent) == shown

    is_percent = re.fullmatch(_NUMBER + "%", sent) is not None
    if not is_percent and not re.fullmatch(_NUMBER, sent):
        is_letter_type = grading_type in _LETTER_GRADING_TYPES
        return is_letter_type and sent.upper() == shown.upper()

    if is_percent:
        if not points_possible:
            return False
        sent_score = float(sent.removesuffix("%")) / 100 * points_possible
    else:
        sent_score = float(sent)
    entered_score = submission.entered_score
    if entered_score is None or not math.isclose(
        entered_score, sent_score, rel_tol=1e-9, abs_tol=1e-9
    ):
        return False
    if grading_type == "points":
        return re.fullmatch(_NUMBER, shown) is not None and math.isclose(
            float(shown), sent_score, rel_tol=1e-9, abs_tol=1e-9
        )
    if grading_type == "percent":
        # Canvas shows percentages to two decimals.
        return (
            is_percent
            and re.fullmatch(_NUMBER + "%", shown) is not None
            and abs(float(shown.removesuffix("%")) - float(sent.removesuffix("%")))
            < 0.0051
        )
    if grading_type not in _LETTER_GRADING_TYPES or not points_possible:
        return False
    if shown.lower() in _PASS_FAIL_GRADES:
        return False
    # Without a visible scheme, only the score can be compared.
    return not scheme or shown == _scheme_letter(
        entered_score / points_possible, scheme
    )


def _scheme_letter(share: float, scheme: list[CanvasGradingSchemeEntry]) -> str:
    """Return the letter the scheme gives a share of the points possible."""
    entries = sorted(scheme, key=lambda entry: entry.value, reverse=True)
    for entry in entries:
        if share >= entry.value:
            return entry.name
    return entries[-1].name


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


@dataclass(frozen=True)
class PostingPreview:
    """What the push preview showed about releasing an assignment's grades.

    Attributes:
        post_manually: The assignment posted grades manually.
        unposted_ids: Students whose previewed grade was not yet visible to them.
        released_ids: Students whose previewed grade already was.
    """

    post_manually: bool
    unposted_ids: frozenset[int]
    released_ids: frozenset[int] = frozenset()


def push_grades(
    client: CanvasClient,
    conn: sqlite_utils.Database,
    grade_data_by_aid: dict[int, dict[int, str]],
    *,
    post_grades: bool = False,
    cover_policy_changes: bool = False,
    previewed: Mapping[int, PostingPreview] | None = None,
) -> list[dict[str, object]]:
    """Bulk-push grades to Canvas, releasing them to students only if approved.

    On an assignment that posts automatically, the push itself releases grades.
    On one that posts manually, pushed grades are released only with
    ``post_grades`` (commitment C5), and only those Canvas shows as sent. The
    posting policy is read live just before each push; a change between that
    read and the push itself cannot be prevented.

    On an assignment that posts manually, the grades are read back after a push
    that includes any grade (clears alone are not). Those Canvas does not show
    as sent are unconfirmed, and the caller must keep them pending. If they
    cannot be read back, all count as pushed.

    An assignment that posts automatically now but did not at the preview, or
    without a preview as last pulled, fails without being sent unless the
    release of every grade in it was approved or already done at the preview.

    Args:
        client: Authenticated Canvas API client.
        conn: SQLite database connection, for the last pulled posting policy
            and student names.
        grade_data_by_aid: ``{assignment_id: {user_id: grade_string}}``. An
            empty grade removes the grade on Canvas and is never released.
        post_grades: The user approved releasing the pushed grades. With
            ``previewed``, this covers only the grades that were unreleased on
            manual-post assignments then.
        cover_policy_changes: The approval covers every pushed grade, whatever
            the preview showed.
        previewed: Posting preview by assignment, as the user saw it.

    Returns:
        List of result dicts with ``ok`` and ``canvas_assignment_id``. A push
        also has ``count``, and if it succeeded ``unreleased`` (grades pushed
        but not visible to students, whose release was not approved) and
        ``release_unknown`` (those cass could not tell about). A release has
        the ``action`` ``posted_to_students``. Failures have an ``error``.
        Unconfirmed grades are left out of those counts and have a failure of
        their own, with their students in ``unconfirmed_ids``.
    """
    results: list[dict[str, object]] = []
    for aid, grade_data in grade_data_by_aid.items():
        seen = None if previewed is None else previewed.get(aid)
        covers_all = post_grades and (cover_policy_changes or previewed is None)
        release_approved = covers_all or (
            post_grades and seen is not None and seen.post_manually
        )
        graded = {uid: g for uid, g in grade_data.items() if is_valid_grade(g)}
        automatic_approved = covers_all or (
            release_approved
            and seen is not None
            and graded.keys() <= seen.unposted_ids | seen.released_ids
        )
        try:
            assignment = client.get_assignment(aid)
            post_manually = get_post_manually(assignment)
            if not post_manually and not automatic_approved:
                if previewed is None:
                    was_automatic = _stored_post_manually(conn, aid) is False
                else:
                    was_automatic = seen is not None and not seen.post_manually
                if not was_automatic:
                    raise RuntimeError(
                        "grades now post automatically on this assignment, so "
                        "pushing would release them to students without approval; "
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

        pushed: dict[str, object] = {
            "canvas_assignment_id": aid,
            "ok": True,
            "count": len(grade_data),
            "unreleased": 0,
            "release_unknown": 0,
        }
        results.append(pushed)
        if not post_manually or not graded:
            continue
        if covers_all:
            approved_ids = set(graded)
        elif release_approved and seen is not None:
            approved_ids = graded.keys() & seen.unposted_ids
        else:
            approved_ids = set()
        try:
            live = {s.user_id: s for s in client.list_submissions(aid)}
            scheme = get_scheme(client, assignment)
        except Exception as e:
            pushed["release_unknown"] = len(graded) - len(approved_ids)
            if approved_ids:
                results.append(_unread_release(aid, len(approved_ids), e))
            continue
        unconfirmed = [
            uid
            for uid, grade in grade_data.items()
            if not _shows_sent(grade, live.get(uid), assignment, scheme)
        ]
        pushed["count"] = len(grade_data) - len(unconfirmed)
        posted_at = {
            uid: live[uid].posted_at for uid in graded if uid not in unconfirmed
        }
        rest = [uid for uid in posted_at if uid not in approved_ids]
        pushed["unreleased"] = sum(posted_at[uid] is None for uid in rest)
        pushed["release_unknown"] = sum(posted_at[uid] is msgspec.UNSET for uid in rest)
        to_release = [
            uid
            for uid in posted_at
            if uid in approved_ids and not isinstance(posted_at[uid], str)
        ]
        if to_release:
            results.append(_release_grades(client, aid, to_release))
        if unconfirmed:
            names = ", ".join(student_name(conn, uid) for uid in unconfirmed)
            results.append(
                {
                    "canvas_assignment_id": aid,
                    "ok": False,
                    "unconfirmed_ids": unconfirmed,
                    "error": f"Canvas does not show the pushed grade for {names}. "
                    "cass kept these pending and did not release them. Check them "
                    "in the Canvas gradebook, then push again or revert.",
                }
            )
    return results


def _stored_post_manually(conn: sqlite_utils.Database, aid: int) -> bool | None:
    """Return the posting policy at the last pull, or None if not stored."""
    row = conn.execute(
        "SELECT post_manually FROM canvas_assignments WHERE canvas_id = ?", [aid]
    ).fetchone()
    return None if row is None or row[0] is None else bool(row[0])


def _unread_release(aid: int, count: int, error: Exception) -> dict[str, object]:
    """Return the result row for grades that could not be read back."""
    return {
        "canvas_assignment_id": aid,
        "action": "posted_to_students",
        "ok": False,
        "error": f"cass released none of {count} pushed grade(s), because it could "
        f"not check them on Canvas: {error}. Post them in the Canvas gradebook.",
    }


def _shows_sent(
    sent: str,
    submission: CanvasSubmissionResponse | None,
    assignment: CanvasAssignmentResponse,
    scheme: list[CanvasGradingSchemeEntry],
) -> bool:
    """Return whether Canvas shows what was sent: the grade, or none for a clear.

    Canvas can complete a push yet ignore or remove a student's grade, and
    someone else may have changed it since. Releasing it would then show the
    student a grade the user did not push.
    """
    if not is_valid_grade(sent):
        return submission is None or not is_valid_grade(submission.entered_grade)
    return submission is not None and shows_pushed_grade(
        sent,
        submission,
        assignment.grading_type,
        assignment.points_possible,
        scheme,
    )


def _release_grades(
    client: CanvasClient, aid: int, user_ids: list[int]
) -> dict[str, object]:
    """Post the students' grades; returns the result row."""
    result: dict[str, object] = {
        "canvas_assignment_id": aid,
        "action": "posted_to_students",
    }
    try:
        progress = client.post_assignment_grades(
            aid, graded_only=True, only_student_ids=user_ids
        )
        if progress is None:
            raise RuntimeError("Canvas did not start posting")
        client.wait_for_progress(progress.id)
    except Exception as e:
        error = (
            f"{len(user_ids)} grade(s) pushed but may not be released to "
            f"students: {e}. Check the Canvas gradebook and post them there."
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
