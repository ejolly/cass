"""``people list`` enrollment filters and the Enrolled column."""

from __future__ import annotations

__docformat__ = "google"

import json
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from cass.actions.config import reset_config, set_config_path
from cass.actions.enrollments import ALL_ENROLLMENT_STATES
from cass.apis.canvas.client import CanvasClient
from cass.apis.canvas.schema import (
    CanvasAssignmentResponse,
    CanvasEnrollment,
    CanvasStudentResponse,
    CanvasSubmissionResponse,
    CanvasUser,
)
from cass.cli import app

runner = CliRunner()


@pytest.fixture
def people_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.time_zone = "America/Los_Angeles"
    c.list_users.return_value = [
        CanvasUser(id=5, name="Ann Lee", sortable_name="Lee, Ann"),
        CanvasUser(id=6, name="Ben Ray", sortable_name="Ray, Ben"),
    ]
    c.list_enrollments.return_value = [
        CanvasEnrollment(
            id=1,
            user_id=5,
            type="StudentEnrollment",
            created_at="2026-10-02T17:00:00Z",
        ),
        CanvasEnrollment(
            id=2,
            user_id=6,
            type="StudentEnrollment",
            created_at="2026-09-01T00:00:00Z",
        ),
    ]
    monkeypatch.setattr("cass.cli.canvas._common.client", lambda *a, **k: c)
    monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
    return c


def test_people_enrolled_column(people_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "people", "list"])
    assert result.exit_code == 0, result.output
    assert "Enrolled" in result.stdout
    assert "2026-10-02 10:00" in result.stdout
    people_client.list_enrollments.assert_called_once_with(
        enrollment_type=None, states=ALL_ENROLLMENT_STATES, include_scores=False
    )


def test_people_enrolled_after_filters(people_client: MagicMock) -> None:
    result = runner.invoke(
        app, ["canvas", "people", "list", "--enrolled-after", "2026-10-01"]
    )
    assert result.exit_code == 0, result.output
    assert "Ann" in result.stdout
    assert "Ben" not in result.stdout


def test_people_state_passes_enrollment_states(people_client: MagicMock) -> None:
    result = runner.invoke(
        app, ["canvas", "people", "list", "--state", "active", "--state", "completed"]
    )
    assert result.exit_code == 0, result.output
    people_client.list_users.assert_called_once_with(states=["active", "completed"])
    bad = runner.invoke(app, ["canvas", "people", "list", "--state", "bogus"])
    assert bad.exit_code == 2


def test_people_json_has_enrolled_at(people_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "people", "list", "--json"])
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    ann = next(r for r in rows if r["id"] == 5)
    assert ann["enrolled_at"] == "2026-10-02T17:00:00Z"


# --- submissions list ---------------------------------------------------------


@pytest.fixture
def submissions_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    c = MagicMock()
    c.__enter__.return_value = c
    c.time_zone = "America/Los_Angeles"
    c.resolve_assignment.return_value = CanvasAssignmentResponse(id=7, name="HW1")
    c.list_submissions.return_value = [
        CanvasSubmissionResponse(
            user_id=6,
            excused=True,
            workflow_state="unsubmitted",
            user=CanvasStudentResponse(id=6, name="Ben Ray", sortable_name="Ray, Ben"),
        ),
        CanvasSubmissionResponse(
            user_id=5,
            late=True,
            workflow_state="submitted",
            submitted_at="2026-10-02T17:00:00Z",
            late_policy_status="late",
            user=CanvasStudentResponse(id=5, name="Ann Lee", sortable_name="Lee, Ann"),
        ),
    ]
    factory = MagicMock(return_value=c)
    monkeypatch.setattr("cass.cli.canvas._common.client", factory)
    monkeypatch.setattr("cass.cli.canvas._common.require_canvas", lambda: None)
    c.factory = factory
    return c


def test_submissions_list_table(submissions_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "submissions", "list", "HW1"])
    assert result.exit_code == 0, result.output
    assert "Submissions: HW1" in result.stdout
    assert "Ann" in result.stdout
    assert "Late policy" in result.stdout
    submissions_client.list_submissions.assert_called_once_with(7, include_user=True)


def test_submissions_list_student_filter(submissions_client: MagicMock) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "list", "HW1", "--student", "6"]
    )
    assert result.exit_code == 0, result.output
    assert "Ben" in result.stdout
    assert "Ann" not in result.stdout
    bad = runner.invoke(
        app, ["canvas", "submissions", "list", "HW1", "--student", "42"]
    )
    assert bad.exit_code == 1
    assert "42" in str(bad.exception)


def test_submissions_list_json(submissions_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "submissions", "list", "HW1", "--json"])
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    for key in (
        "late",
        "missing",
        "excused",
        "late_policy_status",
        "workflow_state",
        "submitted_at",
        "user",
    ):
        assert key in rows[0]


def test_bare_submissions_shows_help(submissions_client: MagicMock) -> None:
    result = runner.invoke(app, ["canvas", "submissions"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    submissions_client.factory.assert_not_called()


# --- submissions excuse / clear-late --------------------------------------------

API = "/api/v1"
CASS_TOML = """\
[canvas]
base_url = "https://canvas.example.com"
course_id = 1
time_zone = "America/Los_Angeles"
"""
HW1 = {"id": 7, "name": "HW1", "published": True, "due_at": "2026-09-30T06:59:00Z"}
HW2 = {
    "id": 8,
    "name": "HW2",
    "published": True,
    "due_at": "2026-10-20T06:59:00Z",
    "group_category_id": 3,
}


def _user(user_id: int, name: str) -> dict[str, object]:
    return {"id": user_id, "name": name, "sortable_name": name}


ANN_HW1 = {
    "user_id": 5,
    "assignment_id": 7,
    "workflow_state": "unsubmitted",
    "missing": True,
    "cached_due_date": "2026-09-30T06:59:00Z",
    "user": _user(5, "Ann"),
}
BEN_HW1 = {
    "user_id": 6,
    "assignment_id": 7,
    "workflow_state": "graded",
    "score": 8,
    "grade": "8",
    "user": _user(6, "Ben"),
}
CY_HW1 = {
    "user_id": 7,
    "assignment_id": 7,
    "workflow_state": "submitted",
    "late": True,
    "user": _user(7, "Cy"),
}
CY_HW2 = {**CY_HW1, "assignment_id": 8}
ANN_HW2 = {
    "user_id": 5,
    "assignment_id": 8,
    "workflow_state": "unsubmitted",
    "cached_due_date": "2026-10-20T06:59:00Z",
    "user": _user(5, "Ann"),
}
SUBMISSIONS = {
    (7, 5): ANN_HW1,
    (7, 6): BEN_HW1,
    (7, 7): CY_HW1,
    (8, 7): CY_HW2,
    (8, 5): ANN_HW2,
}


def _enrollment(
    enrollment_id: int, user_id: int, kind: str, created_at: str
) -> dict[str, object]:
    return {
        "id": enrollment_id,
        "user_id": user_id,
        "type": kind,
        "enrollment_state": "active",
        "created_at": created_at,
    }


GET_ROUTES: dict[str, object] = {
    "/courses/1": {"id": 1, "name": "C", "time_zone": "America/Los_Angeles"},
    "/courses/1/assignments": [HW1, HW2],
    "/courses/1/assignments/7": HW1,
    "/courses/1/assignments/8": HW2,
    "/courses/1/assignments/7/submissions": [ANN_HW1, BEN_HW1, CY_HW1],
    "/courses/1/assignments/8/submissions": [CY_HW2],
    "/courses/1/enrollments": [
        _enrollment(1, 5, "StudentEnrollment", "2026-10-02T17:00:00Z"),
        _enrollment(2, 6, "StudentEnrollment", "2026-09-01T00:00:00Z"),
        _enrollment(3, 99, "StudentViewEnrollment", "2026-10-03T00:00:00Z"),
    ],
    "/courses/1/students/submissions": [ANN_HW1, ANN_HW2],
}


@pytest.fixture(autouse=True)
def reset_cached_config() -> Iterator[None]:
    reset_config()
    set_config_path(None)
    yield
    set_config_path(None)
    reset_config()


@pytest.fixture
def submissions_course(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[httpx.Request]:
    """A project directory plus a fake Canvas that records every request."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cass.toml").write_text(CASS_TOML)
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        path = request.url.path.removeprefix(API)
        match = re.fullmatch(r"/courses/1/assignments/(\d+)/submissions/(\d+)", path)
        if request.method != "GET":
            assert match, path
            return httpx.Response(
                200, json={"user_id": int(match[2]), "assignment_id": int(match[1])}
            )
        if match:
            return httpx.Response(200, json=SUBMISSIONS[(int(match[1]), int(match[2]))])
        return httpx.Response(200, json=GET_ROUTES.get(path, []))

    monkeypatch.setattr(
        "cass.cli.canvas._common.client",
        lambda dry_run=False: CanvasClient(
            "https://canvas.example.com",
            token="t",
            course_id=1,
            transport=httpx.MockTransport(handler),
            time_zone="America/Los_Angeles",
            dry_run=dry_run,
        ),
    )
    return sent


def _writes(sent: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in sent if r.method != "GET"]


def test_excuse_defaults_to_dry_run(submissions_course: list[httpx.Request]) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "excuse", "HW1", "--student", "5"]
    )
    assert result.exit_code == 0, result.output
    assert _writes(submissions_course) == []
    assert re.search(r"excuse .*HW1 .*Ann \(5\)", result.stdout)
    assert re.search(
        r"^\s*PUT /courses/1/assignments/7/submissions/5", result.stdout, re.MULTILINE
    )
    assert "--apply" in result.stderr


def test_excuse_apply_sends_put(submissions_course: list[httpx.Request]) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "excuse", "HW1", "--student", "5", "--apply"]
    )
    assert result.exit_code == 0, result.output
    (write,) = _writes(submissions_course)
    assert write.method == "PUT"
    assert write.url.path == "/api/v1/courses/1/assignments/7/submissions/5"
    assert write.content.decode() == "submission%5Bexcuse%5D=true"
    assert "Excused 1 submission(s)." in result.stdout


def test_excuse_graded_needs_include_graded(
    submissions_course: list[httpx.Request],
) -> None:
    base = ["canvas", "submissions", "excuse", "HW1", "--student", "6", "--apply"]
    result = runner.invoke(app, base)
    assert result.exit_code == 0, result.output
    assert _writes(submissions_course) == []
    assert "skip" in result.stdout
    assert "graded (8)" in result.stdout

    result = runner.invoke(app, [*base, "--include-graded"])
    assert result.exit_code == 0, result.output
    (write,) = _writes(submissions_course)
    assert write.url.path == "/api/v1/courses/1/assignments/7/submissions/6"


def test_excuse_enrolled_after(submissions_course: list[httpx.Request]) -> None:
    result = runner.invoke(
        app,
        [
            "canvas",
            "submissions",
            "excuse",
            "--enrolled-after",
            "2026-10-01",
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output
    (write,) = _writes(submissions_course)
    assert write.url.path == "/api/v1/courses/1/assignments/7/submissions/5"


def test_clear_late_apply_sends_none(submissions_course: list[httpx.Request]) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "clear-late", "HW1", "--student", "7", "--apply"]
    )
    assert result.exit_code == 0, result.output
    (write,) = _writes(submissions_course)
    assert write.content.decode() == "submission%5Blate_policy_status%5D=none"
    assert "Cleared late on 1 submission(s)." in result.stdout


def test_clear_late_group_assignment_warns(
    submissions_course: list[httpx.Request],
) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "clear-late", "HW2", "--student", "7"]
    )
    assert result.exit_code == 0, result.output
    assert "whole group" in result.stderr
    assert "HW2" in result.stderr
    assert "whole group" not in result.stdout


@pytest.mark.parametrize("command", ["excuse", "clear-late"])
@pytest.mark.parametrize(
    "args",
    [
        [],
        ["HW1", "--student", "5", "--enrolled-after", "2026-10-01"],
        ["--student", "5"],
    ],
)
def test_bad_target_flags_exit_2(
    submissions_course: list[httpx.Request], command: str, args: list[str]
) -> None:
    result = runner.invoke(app, ["canvas", "submissions", command, *args])
    assert result.exit_code == 2, result.output
    assert submissions_course == []


@pytest.mark.parametrize("command", ["excuse", "clear-late"])
def test_apply_and_dry_run_conflict(
    submissions_course: list[httpx.Request], command: str
) -> None:
    result = runner.invoke(
        app,
        [
            "canvas",
            "submissions",
            command,
            "HW1",
            "--student",
            "5",
            "--apply",
            "--dry-run",
        ],
    )
    assert result.exit_code == 2, result.output
    assert submissions_course == []


def test_unknown_student_exits_1_without_writes(
    submissions_course: list[httpx.Request],
) -> None:
    result = runner.invoke(
        app, ["canvas", "submissions", "excuse", "HW1", "--student", "42", "--apply"]
    )
    assert result.exit_code == 1
    assert "42" in str(result.exception)
    assert _writes(submissions_course) == []


def test_no_matching_submissions(submissions_course: list[httpx.Request]) -> None:
    result = runner.invoke(
        app,
        [
            "canvas",
            "submissions",
            "excuse",
            "--enrolled-after",
            "2026-12-01",
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "No matching submissions." in result.stderr
    assert _writes(submissions_course) == []
