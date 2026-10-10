"""Tests for cass.apis.canvas.dry_run — recording writes instead of sending them."""

import httpx
import pytest

from cass.actions.quizzes import QuestionSpec, QuizSpec
from cass.apis.canvas.client import CanvasAPIError, CanvasClient
from cass.apis.canvas.dry_run import PlannedRequest, format_plan
from cass.apis.canvas.schema import CanvasQuiz

# --- Plan rendering ---


def test_format_plan_line():
    planned = PlannedRequest(
        "POST",
        "/courses/1/quizzes/-1/questions",
        {"question": {"question_name": "Q1", "points_possible": 1}},
    )
    assert format_plan([planned]) == [
        "POST /courses/1/quizzes/<new 1>/questions  question_name=Q1  points_possible=1"
    ]


def test_format_plan_truncates_values():
    planned = PlannedRequest("PUT", "/courses/1", {"description": "x" * 100})
    (line,) = format_plan([planned])
    value = line.split("description=", 1)[1]
    assert len(value) == 60
    assert value == "x" * 57 + "..."


def test_format_plan_renders_nested_values_as_json():
    planned = PlannedRequest("POST", "/x", {"answers": [{"answer_text": "A"}]})
    assert format_plan([planned]) == ['POST /x  answers=[{"answer_text":"A"}]']


# --- Dry-run client ---

_GET_RESPONSES = {
    "/courses/1/tabs": (
        200,
        [{"id": "files", "label": "Files", "hidden": False, "position": 3}],
    ),
    "/courses/1/quizzes/123": (200, {"id": 123, "title": "Old", "allowed_attempts": 1}),
    "/courses/1/quizzes/999": (404, {"message": "not found"}),
}


def _make_client(sent: list[httpx.Request], *, dry_run: bool = True) -> CanvasClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        path = request.url.path.removeprefix("/api/v1")
        if request.method == "GET" and path in _GET_RESPONSES:
            status, body = _GET_RESPONSES[path]
            return httpx.Response(status, json=body)
        return httpx.Response(500, json={"message": "unexpected request"})

    return CanvasClient(
        "https://canvas.example.com",
        token="t",
        course_id=1,
        transport=httpx.MockTransport(handler),
        time_zone="America/Los_Angeles",
        dry_run=dry_run,
    )


@pytest.fixture
def dry():
    sent: list[httpx.Request] = []
    return _make_client(sent), sent


def writes(sent: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in sent if r.method != "GET"]


def test_create_quiz_records_chain(dry):
    client, sent = dry
    spec = QuizSpec(
        title="Week 1",
        quiz_type="survey",
        questions=[QuestionSpec(text="a"), QuestionSpec(text="b")],
    )
    quiz = client.create_quiz(spec)
    assert [(r.method, r.path) for r in client.planned_requests] == [
        ("POST", "/courses/1/quizzes"),
        ("POST", "/courses/1/quizzes/-1/questions"),
        ("POST", "/courses/1/quizzes/-1/questions"),
        ("PUT", "/courses/1/quizzes/-1"),
    ]
    assert isinstance(quiz, CanvasQuiz)
    assert quiz.title == "Week 1"
    assert quiz.id == -1
    assert writes(sent) == []
    assert not any("/-1" in str(r.url) for r in sent)


def test_update_tab_keeps_string_id_and_real_label(dry):
    client, sent = dry
    tab = client.update_tab("files", hidden=True)
    assert tab.id == "files"
    assert tab.label == "Files"
    assert tab.hidden is True
    assert writes(sent) == []
    assert len(sent) == 1
    assert sent[0].method == "GET"
    assert sent[0].url.path == "/api/v1/courses/1/tabs"
    assert sent[0].url.params["per_page"] == "100"


def test_upload_file_records_both_posts(dry, tmp_path, monkeypatch):
    client, sent = dry
    path = tmp_path / "notes.txt"
    path.write_text("hello")

    def fail_post(*args, **kwargs):
        pytest.fail("httpx.post must not be called during a dry run")

    monkeypatch.setattr(httpx, "post", fail_post)
    uploaded = client.upload_file(str(path))
    assert uploaded.display_name == "notes.txt"
    planned = client.planned_requests
    assert [(r.method, r.path) for r in planned] == [
        ("POST", "/courses/1/files"),
        ("POST", "https://dry-run.invalid/upload"),
    ]
    assert planned[1].body["file"] == "notes.txt"
    assert writes(sent) == []


def test_existing_resource_fetched_once_and_merged(dry):
    client, sent = dry
    client.update_quiz(123, {"title": "New"})
    quiz = client.update_quiz(123, {"allowed_attempts": 3})
    assert quiz.id == 123
    assert quiz.title == "New"
    assert quiz.allowed_attempts == 3
    gets = [r for r in sent if r.url.path == "/api/v1/courses/1/quizzes/123"]
    assert len(gets) == 1
    assert gets[0].method == "GET"


def test_get_to_created_path_is_served_locally(dry):
    client, sent = dry
    client.create_module("Week 9")
    assert client.get_module(-1).name == "Week 9"
    assert not any("/-1" in str(r.url) for r in sent)


def test_get_under_placeholder_is_not_sent(dry):
    client, sent = dry
    resp = client.request("GET", "/courses/1/quizzes/-1/questions")
    assert resp.json() == []
    assert sent == []


def test_write_under_unstored_placeholder_is_not_fetched(dry):
    client, sent = dry
    client.request("POST", "/courses/1/assignments", data={"assignment[name]": "A"})
    resp = client.request(
        "PUT",
        "/courses/1/assignments/-1/submissions/5",
        data={"submission[posted_grade]": "10"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"posted_grade": "10", "id": 5}
    assert sent == []


def test_placeholders_count_down_per_client(dry):
    client, _ = dry
    assert client.create_module("A").id == -1
    assert client.create_module("B").id == -2
    other = _make_client([])
    assert other.create_module("C").id == -1


def test_failed_real_get_raises(dry):
    client, _ = dry
    with pytest.raises(CanvasAPIError) as excinfo:
        client.update_quiz(999, {"title": "x"})
    assert excinfo.value.status_code == 404


def test_empty_string_clears_field(dry):
    client, _ = dry
    quiz = client.update_quiz(123, {"time_limit": ""})
    assert quiz.time_limit is None


def test_not_dry_run_has_empty_plan():
    client = _make_client([], dry_run=False)
    assert client.dry_run is False
    assert client.planned_requests == []
