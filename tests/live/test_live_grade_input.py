"""Live test: which grades Canvas records as entered, per grading type.

Canvas accepts any text through a bulk grade update. Text it cannot read
removes the existing grade, so ``accepts_grade`` must refuse it.
"""

from __future__ import annotations

__docformat__ = "google"

import time
from uuid import uuid4

import pytest
from live_course import get_test_student_id

from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.sync import accepts_grade, get_scheme_letters


def _entered_grade(client: CanvasClient, assignment_id: int, user_id: int):
    """The user's (entered grade, score), once Canvas has made the submission."""
    deadline = time.monotonic() + 30
    while True:
        for submission in client.list_submissions(assignment_id):
            if submission.user_id == user_id:
                return submission.entered_grade, submission.score
        assert time.monotonic() < deadline, "no submission row after 30s"
        time.sleep(2)


@pytest.mark.parametrize(
    ("grading_type", "existing", "accepted", "refused"),
    [
        (
            "points",
            "8",
            {"9": ("9", 9.0), "95%": ("9.5", 9.5)},
            {
                " ": (None, None),
                "9O": (None, None),
                "B+": (None, None),
                " 9 ": (None, None),
                "complete": ("10", 10.0),
            },
        ),
        ("percent", "80%", {"95%": ("95%", 9.5)}, {"95": ("950%", 95.0)}),
        (
            "letter_grade",
            "B",
            {"B+": ("B+", 8.9), "9": ("A-", 9.0)},
            {"Z": (None, None), "A+": (None, None), "complete": ("A", 10.0)},
        ),
        (
            "pass_fail",
            "complete",
            {"fail": ("incomplete", 0.0)},
            {"9": (None, None), "Complete": ("incomplete", 0.0)},
        ),
    ],
)
def test_accepts_grade_matches_canvas(
    practice: CanvasClient, grading_type, existing, accepted, refused
):
    student_id = get_test_student_id(practice)
    assignment = practice.create_assignment(
        f"cass-live grade input {uuid4().hex[:8]}",
        points_possible=10,
        grading_type=grading_type,
        published=True,
    )

    def push(grade: str):
        progress = practice.bulk_push_grades(assignment.id, {student_id: grade})
        practice.wait_for_progress(progress.id)
        return _entered_grade(practice, assignment.id, student_id)

    try:
        _entered_grade(practice, assignment.id, student_id)
        live = practice.get_assignment(assignment.id)
        assert live.grading_type == grading_type
        letters = get_scheme_letters(practice, live)
        for grade, recorded in (accepted | refused).items():
            assert push(existing)[0] == existing
            assert push(grade) == recorded, grade
            if grade != " 9 ":  # cass removes the spaces before pushing
                assert accepts_grade(grade, grading_type, letters) is (
                    grade in accepted
                ), grade
    finally:
        practice.delete_assignment(assignment.id)
