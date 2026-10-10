"""Live test: late-enrollment commands and submission status changes."""

from __future__ import annotations

__docformat__ = "google"

import contextlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from live_course import get_test_student_id
from typer.testing import CliRunner

from cass.actions.config import get_config
from cass.actions.enrollments import fetch_all_enrollments
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.dry_run import format_plan
from cass.apis.canvas.times import parse_when, same_instant
from cass.cli import app

runner = CliRunner()


def _invoke(*args: str) -> str:
    result = runner.invoke(app, ["canvas", *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def _has_row(output: str, action: str) -> bool:
    """True when a plan table row starts with *action*."""
    return re.search(rf"^\s*{action}\b", output, re.MULTILINE) is not None


def _json_lines(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _reread(practice: CanvasClient, assignment_id: int, user_id: int):
    (sub,) = practice.list_student_submissions(
        [user_id], assignment_ids=[assignment_id]
    )
    return sub


@pytest.mark.usefixtures("practice_cli_client")
def test_submission_status_round_trip(practice: CanvasClient):
    tag = uuid4().hex[:8]
    ts = get_test_student_id(practice)
    due = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = practice.create_assignment(
        f"cass-live submissions {tag}",
        points_possible=10,
        due_at=due,
        submission_types=["online_text_entry"],
        published=True,
    )
    try:
        # Assumptions 3, 5: submissions list carries the status fields and the
        # student's own due date.
        lines = _json_lines(_invoke("submissions", "list", str(a.id), "--json"))
        line = next(row for row in lines if row["user_id"] == ts)
        for key in (
            "late",
            "missing",
            "excused",
            "late_policy_status",
            "cached_due_date",
        ):
            assert key in line
        assert same_instant(line["cached_due_date"], a.due_at)

        # Assumption 4: /students/submissions answers for one student + assignment.
        assert len(practice.list_student_submissions([ts], assignment_ids=[a.id])) == 1

        # Assumption 6: late_policy_status=none clears late and missing.
        assert practice.update_submission(a.id, ts, late_policy_status="late").late
        dry = _invoke("submissions", "clear-late", str(a.id), "--student", str(ts))
        assert _has_row(dry, "clear-late")
        assert _reread(practice, a.id, ts).late is True
        _invoke("submissions", "clear-late", str(a.id), "--student", str(ts), "--apply")
        cleared = _reread(practice, a.id, ts)
        assert cleared.late is False
        assert cleared.missing is False
        assert cleared.late_policy_status == "none"

        # Assumption 7: excusing a graded submission clears its grade.
        assert practice.push_grade(a.id, ts, "8")
        skipped = _invoke("submissions", "excuse", str(a.id), "--student", str(ts))
        assert re.search(r"^\s*skip\b.*graded \(8\)", skipped, re.MULTILINE)
        _invoke(
            "submissions",
            *("excuse", str(a.id), "--student", str(ts)),
            *("--include-graded", "--apply"),
        )
        excused = _reread(practice, a.id, ts)
        assert excused.excused is True
        assert excused.score is None
        assert excused.grade is None

        # Assumption 8: setting a late status un-excuses.
        unexcused = practice.update_submission(a.id, ts, late_policy_status="none")
        assert not unexcused.excused
    finally:
        with contextlib.suppress(Exception):
            practice.delete_assignment(a.id)


@pytest.mark.usefixtures("practice_cli_client")
def test_enrollment_dates_and_roster(practice: CanvasClient):
    ts = get_test_student_id(practice)

    # Assumption 1: enrollments of every type and state paginate and have dates.
    enrollments = fetch_all_enrollments(practice)
    assert enrollments
    for enrollment in enrollments:
        assert enrollment.created_at is not None
        assert parse_when(enrollment.created_at, practice.time_zone)
    assert any(e.type == "TeacherEnrollment" for e in enrollments)

    # Assumption 2: the roster has enrolled_at and never lists the Test Student.
    people = _json_lines(_invoke("people", "list", "--json"))
    assert people
    assert all("enrolled_at" in person for person in people)
    assert all(person["id"] != ts for person in people)

    out = _invoke("submissions", "excuse", "--enrolled-after", "2000-01-01")
    assert f"({ts})" not in out
    assert f"/submissions/{ts}" not in out


def test_enrolled_after_dry_run_on_real_course(
    real_course: CanvasClient, monkeypatch: pytest.MonkeyPatch
):
    """Read-only smoke test: exercises enrollment paging on a real roster."""
    clients: list[CanvasClient] = []

    def dry_run_client(dry_run: bool = False) -> CanvasClient:
        # Always a dry run, whatever the command asks for.
        client = CanvasClient(
            get_config().canvas_base_url,
            course_id=real_course.course_id,
            auth=real_course.auth,
            time_zone=real_course.time_zone,
            dry_run=True,
        )
        clients.append(client)
        return client

    monkeypatch.setattr("cass.cli.canvas._common.client", dry_run_client)
    # Read the Test Student's enrollment; get_test_student_id would create one
    # in the real course, which must stay read-only.
    test_students = real_course.get_all(
        real_course.course_path("/enrollments"),
        params=[("type[]", "StudentViewEnrollment")],
    )
    ts = test_students[0]["user_id"] if test_students else None
    since = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%d")

    out = _invoke("submissions", "excuse", "--enrolled-after", since)

    assert clients
    planned = [r for c in clients for r in c.planned_requests]
    pattern = re.compile(
        rf"^PUT /courses/{real_course.course_id}/assignments/\d+/submissions/\d+\b"
    )
    for line in format_plan(planned):
        assert pattern.match(line), line
        assert "submission[excuse]" in line
    # Zero planned requests is fine: nobody may have enrolled recently.
    rows = re.findall(r"^\s*(excuse|skip)\b", out, re.MULTILINE)
    assert len([r for r in rows if r == "excuse"]) == len(planned)
    if ts is not None:
        assert f"({ts})" not in out
        assert all(not r.path.endswith(f"/submissions/{ts}") for r in planned)
