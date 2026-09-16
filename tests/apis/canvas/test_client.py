"""Tests for cass.canvas.client — CanvasClient typed API client."""

import httpx
import msgspec
import pytest

from cass.apis.canvas.schema import (
    CanvasAnnouncement,
    CanvasAssignmentGroup,
    CanvasAssignmentResponse,
    CanvasCalendarEvent,
    CanvasCourse,
    CanvasEnrollment,
    CanvasFile,
    CanvasFolder,
    CanvasModule,
    CanvasModuleItem,
    CanvasProgress,
    CanvasQuiz,
    CanvasSection,
    CanvasStudentResponse,
    CanvasSubmissionResponse,
    CanvasTab,
    CanvasUser,
)

# --- Model decoding tests ---


class TestModels:
    """Ensure all Canvas API structs decode from representative JSON."""

    def test_canvas_course(self):
        data = {
            "id": 123,
            "name": "Intro to Psych",
            "course_code": "PSYC-101",
            "workflow_state": "available",
            "default_view": "modules",
            "enrollment_term_id": 5,
            "total_students": 42,
            "time_zone": "America/Los_Angeles",
            "extra_field": "ignored",
        }
        c = msgspec.convert(data, CanvasCourse, strict=False)
        assert c.id == 123
        assert c.name == "Intro to Psych"
        assert c.total_students == 42

    def test_canvas_student(self):
        data = {
            "id": 247302,
            "name": "Alice Smith",
            "sortable_name": "Smith, Alice",
            "email": "alice@ucsd.edu",
            "sis_user_id": "A12345678",
            "login_id": "asmith",
            "short_name": "Alice",
            "created_at": "2025-05-07T10:57:45-07:00",
        }
        s = msgspec.convert(data, CanvasStudentResponse, strict=False)
        assert s.id == 247302
        assert s.sortable_name == "Smith, Alice"
        assert s.sis_user_id == "A12345678"

    def test_canvas_enrollment_with_nested_grades(self):
        """Enrollment scores live inside a nested 'grades' dict, not top-level."""
        data = {
            "id": 10,
            "user_id": 247302,
            "type": "StudentEnrollment",
            "enrollment_state": "active",
            "role": "StudentEnrollment",
            "course_section_id": 123,
            "grades": {
                "html_url": "https://canvas.example.com/courses/1/grades/247302",
                "current_score": 87.5,
                "final_score": 85.0,
                "current_grade": "B",
                "final_grade": "B",
                "unposted_current_score": 90.0,
                "unposted_final_score": 88.0,
            },
            "course_id": 1,
            "sis_user_id": "A12345678",
            "html_url": "https://canvas.example.com/courses/1/users/247302",
        }
        enr = msgspec.convert(data, CanvasEnrollment, strict=False)
        assert enr.user_id == 247302
        assert enr.grades.final_score == 85.0
        assert enr.grades.current_score == 87.5
        assert enr.grades.final_grade == "B"
        assert enr.grades.current_grade == "B"
        # Properties used by egrades.py
        assert enr.computed_final_score == 85.0
        assert enr.computed_current_score == 87.5

    def test_canvas_enrollment_without_grades(self):
        """Enrollment without include[]=total_scores has no grades dict."""
        data = {
            "id": 10,
            "user_id": 1,
            "type": "StudentEnrollment",
            "enrollment_state": "active",
        }
        enr = msgspec.convert(data, CanvasEnrollment, strict=False)
        assert enr.computed_final_score is None
        assert enr.computed_current_score is None

    def test_canvas_user_with_enrollments(self):
        data = {
            "id": 1,
            "name": "Alice Smith",
            "sortable_name": "Smith, Alice",
            "email": "alice@ucsd.edu",
            "enrollments": [
                {
                    "id": 10,
                    "user_id": 1,
                    "type": "StudentEnrollment",
                    "enrollment_state": "active",
                    "role": "StudentEnrollment",
                    "grades": {
                        "current_score": 92.0,
                        "final_score": 90.0,
                    },
                }
            ],
        }
        u = msgspec.convert(data, CanvasUser, strict=False)
        assert u.name == "Alice Smith"
        assert len(u.enrollments) == 1
        assert u.enrollments[0].role == "StudentEnrollment"
        assert u.enrollments[0].computed_final_score == 90.0

    def test_canvas_section(self):
        data = {
            "id": 456,
            "name": "Section A",
            "sis_section_id": "32146",
            "course_id": 1,
            "created_at": "2025-12-17T10:45:13Z",
        }
        s = msgspec.convert(data, CanvasSection, strict=False)
        assert s.name == "Section A"
        assert s.sis_section_id == "32146"

    def test_canvas_module(self):
        data = {
            "id": 50,
            "name": "Week 1",
            "position": 1,
            "published": True,
            "items_count": 3,
            "items_url": "https://canvas.example.com/api/v1/courses/1/modules/50/items",
        }
        m = msgspec.convert(data, CanvasModule, strict=False)
        assert m.name == "Week 1"
        assert m.published is True
        assert m.items_count == 3

    def test_canvas_module_item(self):
        data = {
            "id": 100,
            "title": "Lecture Slides",
            "type": "File",
            "content_id": 999,
            "position": 2,
            "published": True,
            "module_id": 50,
        }
        mi = msgspec.convert(data, CanvasModuleItem, strict=False)
        assert mi.type == "File"
        assert mi.content_id == 999

    def test_canvas_assignment_expanded(self):
        data = {
            "id": 200,
            "name": "Homework 1",
            "points_possible": 10.0,
            "due_at": "2026-01-20T23:59:59Z",
            "published": True,
            "submission_types": ["online_url"],
            "grading_type": "points",
            "assignment_group_id": 5,
            "position": 1,
            "html_url": "https://canvas.example.com/courses/1/assignments/200",
            "description": "<p>Submit your work</p>",
            "has_submitted_submissions": True,
            "workflow_state": "published",
        }
        a = msgspec.convert(data, CanvasAssignmentResponse, strict=False)
        assert a.published is True
        assert a.submission_types == ["online_url"]
        assert a.grading_type == "points"
        assert a.assignment_group_id == 5

    def test_canvas_assignment_group(self):
        data = {
            "id": 5,
            "name": "Homework",
            "position": 1,
            "group_weight": 30.0,
            "rules": {"drop_lowest": 1},
        }
        g = msgspec.convert(data, CanvasAssignmentGroup, strict=False)
        assert g.group_weight == 30.0
        assert g.rules == {"drop_lowest": 1}

    def test_canvas_quiz(self):
        data = {
            "id": 300,
            "title": "Midterm Quiz",
            "quiz_type": "assignment",
            "published": True,
            "time_limit": 60,
            "question_count": 20,
            "points_possible": 100.0,
            "assignment_id": 200,
        }
        q = msgspec.convert(data, CanvasQuiz, strict=False)
        assert q.time_limit == 60
        assert q.question_count == 20

    def test_canvas_file(self):
        data = {
            "id": 400,
            "display_name": "slides.pdf",
            "filename": "slides.pdf",
            "size": 1048576,
            "content-type": "application/pdf",
            "url": "https://canvas.example.com/files/400/download",
            "folder_id": 10,
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-01-15T10:00:00Z",
        }
        f = msgspec.convert(data, CanvasFile, strict=False)
        assert f.display_name == "slides.pdf"
        assert f.size == 1048576

    def test_canvas_folder(self):
        data = {
            "id": 10,
            "name": "slides",
            "full_name": "course files/slides",
            "parent_folder_id": 1,
            "files_count": 5,
            "folders_count": 0,
        }
        f = msgspec.convert(data, CanvasFolder, strict=False)
        assert f.full_name == "course files/slides"

    def test_canvas_announcement(self):
        data = {
            "id": 500,
            "title": "Welcome!",
            "message": "<p>Hello class</p>",
            "posted_at": "2026-01-10T08:00:00Z",
            "user_name": "Dr. Smith",
        }
        a = msgspec.convert(data, CanvasAnnouncement, strict=False)
        assert a.user_name == "Dr. Smith"

    def test_canvas_calendar_event(self):
        data = {
            "id": 234,
            "title": "Midterm review",
            "start_at": "2026-10-19T15:00:00-07:00",
            "end_at": "2026-10-19T16:00:00-07:00",
            "description": "<b>Bring questions</b>",
            "location_name": "Room 237",
            "context_code": "course_123",
            "workflow_state": "active",
            "all_day": False,
            "html_url": "https://canvas.example.com/calendar?event_id=234",
            "child_events": [],
        }
        e = msgspec.convert(data, CanvasCalendarEvent, strict=False)
        assert e.id == 234
        assert e.location_name == "Room 237"
        assert e.all_day is False

    def test_canvas_assignment_with_null_points(self):
        """Quiz-backed assignments report null points until the quiz has questions."""
        data = {"id": 1, "name": "Quiz shell", "points_possible": None}
        a = msgspec.convert(data, CanvasAssignmentResponse, strict=False)
        assert a.points_possible is None

    def test_canvas_submission_response(self):
        """CanvasSubmissionResponse with all fields from real API."""
        data = {
            "id": 93010250,
            "user_id": 257791,
            "assignment_id": 1089019,
            "grade": "10",
            "score": 10.0,
            "submitted_at": None,
            "late": False,
            "missing": False,
            "seconds_late": 0.0,
            "workflow_state": "graded",
            "entered_grade": "10",
            "entered_score": 10.0,
            "excused": False,
            "graded_at": "2026-02-04T20:58:11Z",
            "posted_at": "2026-02-04T20:58:11Z",
        }
        s = msgspec.convert(data, CanvasSubmissionResponse, strict=False)
        assert s.user_id == 257791
        assert s.grade == "10"
        assert s.score == 10.0
        assert s.workflow_state == "graded"
        assert s.late is False

    def test_canvas_submission_response_ungraded(self):
        """Ungraded submission has null grade and score."""
        data = {
            "id": 93010251,
            "user_id": 257791,
            "assignment_id": 1089019,
            "grade": None,
            "score": None,
            "workflow_state": "unsubmitted",
        }
        s = msgspec.convert(data, CanvasSubmissionResponse, strict=False)
        assert s.grade is None
        assert s.score is None
        assert s.workflow_state == "unsubmitted"

    def test_canvas_tab(self):
        data = {
            "id": "modules",
            "label": "Modules",
            "type": "internal",
            "position": 2,
            "visibility": "public",
            "hidden": False,
        }
        t = msgspec.convert(data, CanvasTab, strict=False)
        assert t.id == "modules"  # string ID
        assert t.hidden is False

    def test_canvas_progress(self):
        data = {
            "id": 42,
            "workflow_state": "completed",
            "completion": 100.0,
            "message": None,
            "tag": "submissions_update",
            "url": "https://canvas.example.com/api/v1/progress/42",
        }
        p = msgspec.convert(data, CanvasProgress, strict=False)
        assert p.id == 42
        assert p.workflow_state == "completed"
        assert p.completion == 100.0

    def test_canvas_progress_defaults(self):
        data = {"id": 99, "workflow_state": "queued"}
        p = msgspec.convert(data, CanvasProgress, strict=False)
        assert p.id == 99
        assert p.completion is None
        assert p.message is None


# --- CanvasClient unit tests (mocked HTTP) ---


class _MockTransport(httpx.BaseTransport):
    """Transport that returns pre-configured responses."""

    def __init__(self):
        self.responses: list[httpx.Response] = []
        self.requests: list[httpx.Request] = []
        self._idx = 0

    def add(
        self, status: int = 200, json_data: object = None, headers: dict | None = None
    ):
        resp = httpx.Response(
            status,
            json=json_data,
            headers=headers or {},
        )
        self.responses.append(resp)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._idx >= len(self.responses):
            return httpx.Response(500, json={"error": "no more mocked responses"})
        resp = self.responses[self._idx]
        self._idx += 1
        return resp


@pytest.fixture
def mock_client(monkeypatch):
    """Return a CanvasClient with mocked HTTP transport."""
    from cass.apis.canvas.client import CanvasClient

    transport = _MockTransport()
    client = CanvasClient.__new__(CanvasClient)
    client._base_url = "https://canvas.example.com/api/v1"
    client._token = "test-token"
    client.course_id = 1
    client._http = httpx.Client(
        base_url="https://canvas.example.com/api/v1",
        headers={
            "Authorization": "Bearer test-token",
            "User-Agent": "cass-cli/test",
        },
        transport=transport,
        timeout=5.0,
    )
    return client, transport


class TestCanvasClient:
    def test_get_course(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data={
                "id": 1,
                "name": "Test Course",
                "course_code": "TST-101",
                "workflow_state": "available",
            }
        )
        course = client.get_course()
        assert course.name == "Test Course"
        assert "include[]=total_students" in str(transport.requests[0].url)

    def test_list_modules(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {
                    "id": 1,
                    "name": "Week 1",
                    "position": 1,
                    "published": True,
                    "items_count": 2,
                },
                {
                    "id": 2,
                    "name": "Week 2",
                    "position": 2,
                    "published": False,
                    "items_count": 0,
                },
            ]
        )
        modules = client.list_modules()
        assert len(modules) == 2
        assert modules[0].name == "Week 1"

    def test_list_assignments(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": 10, "name": "HW1", "points_possible": 10, "published": True},
            ]
        )
        assignments = client.list_assignments()
        assert len(assignments) == 1
        assert assignments[0].published is True

    def test_list_quizzes(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {
                    "id": 20,
                    "title": "Quiz 1",
                    "quiz_type": "assignment",
                    "published": True,
                },
            ]
        )
        quizzes = client.list_quizzes()
        assert len(quizzes) == 1
        assert quizzes[0].title == "Quiz 1"

    def test_list_announcements(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {
                    "id": 30,
                    "title": "Welcome",
                    "message": "<p>Hi</p>",
                    "user_name": "Prof",
                },
            ]
        )
        anns = client.list_announcements()
        assert len(anns) == 1
        assert anns[0].user_name == "Prof"

    def test_list_calendar_events_defaults_to_all_events(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": 234, "title": "Midterm review", "context_code": "course_1"},
            ]
        )
        events = client.list_calendar_events()
        assert len(events) == 1
        assert events[0].title == "Midterm review"
        url = str(transport.requests[0].url)
        assert "/calendar_events?" in url
        assert "context_codes[]=course_1" in url
        assert "type=event" in url
        assert "all_events=true" in url

    def test_list_calendar_events_with_date_range(self, mock_client):
        client, transport = mock_client
        transport.add(json_data=[])
        client.list_calendar_events(start_date="2026-10-01", end_date="2026-10-31")
        url = str(transport.requests[0].url)
        assert "start_date=2026-10-01" in url
        assert "end_date=2026-10-31" in url
        assert "all_events" not in url

    def test_create_calendar_event(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data={
                "id": 235,
                "title": "Office hours",
                "start_at": "2026-10-20T10:00:00Z",
                "context_code": "course_1",
            }
        )
        event = client.create_calendar_event(
            "Office hours",
            start_at="2026-10-20T10:00:00Z",
            end_at="2026-10-20T11:00:00Z",
            location_name="Room 237",
        )
        assert event.id == 235
        req = transport.requests[0]
        assert req.method == "POST"
        assert str(req.url).endswith("/calendar_events")
        body = req.content.decode()
        assert "calendar_event%5Bcontext_code%5D=course_1" in body
        assert "calendar_event%5Btitle%5D=Office+hours" in body
        assert "calendar_event%5Blocation_name%5D=Room+237" in body
        assert "description" not in body

    def test_update_calendar_event(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 235, "title": "OH (moved)"})
        event = client.update_calendar_event(235, title="OH (moved)")
        assert event.title == "OH (moved)"
        req = transport.requests[0]
        assert req.method == "PUT"
        assert str(req.url).endswith("/calendar_events/235")
        assert "calendar_event%5Btitle%5D=OH" in req.content.decode()

    def test_delete_calendar_event(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 235})
        client.delete_calendar_event(235)
        req = transport.requests[0]
        assert req.method == "DELETE"
        assert str(req.url).endswith("/calendar_events/235")

    def test_resolve_tab_by_id(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": "syllabus", "label": "Syllabus"},
                {"id": "context_external_tool_5826", "label": "Media Gallery"},
            ]
        )
        assert client.resolve_tab("context_external_tool_5826").label == "Media Gallery"

    def test_resolve_tab_by_label_case_insensitive(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": "syllabus", "label": "Syllabus"},
                {"id": "context_external_tool_5826", "label": "Media Gallery"},
            ]
        )
        assert client.resolve_tab("media gallery").id == "context_external_tool_5826"

    def test_resolve_tab_not_found(self, mock_client):
        client, transport = mock_client
        transport.add(json_data=[{"id": "syllabus", "label": "Syllabus"}])
        with pytest.raises(RuntimeError, match="Tab not found: nope"):
            client.resolve_tab("nope")

    def test_list_tabs(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": "home", "label": "Home", "type": "internal", "position": 1},
            ]
        )
        tabs = client.list_tabs()
        assert len(tabs) == 1
        assert tabs[0].id == "home"

    def test_create_module(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 99, "name": "New Module", "position": 5})
        mod = client.create_module("New Module", position=5)
        assert mod.id == 99
        req = transport.requests[0]
        assert req.method == "POST"

    def test_create_module_item_omits_title_when_not_given(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 7, "title": "HW1", "type": "Assignment"})
        item = client.create_module_item(5, item_type="Assignment", content_id=42)
        assert item.title == "HW1"
        body = transport.requests[0].content.decode()
        assert "module_item%5Btype%5D=Assignment" in body
        assert "module_item%5Bcontent_id%5D=42" in body
        assert "title" not in body

    def test_create_module_item_sends_explicit_title(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 7, "title": "Custom", "type": "Assignment"})
        client.create_module_item(
            5, item_type="Assignment", content_id=42, title="Custom"
        )
        assert "module_item%5Btitle%5D=Custom" in transport.requests[0].content.decode()

    def test_create_quiz_has_no_points_param(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 20, "title": "Q", "quiz_type": "assignment"})
        client.create_quiz("Q")
        assert "points" not in transport.requests[0].content.decode()
        with pytest.raises(TypeError):
            client.create_quiz("Q", points_possible=5)  # pyright: ignore[reportCallIssue]

    def test_create_assignment_group_sends_top_level_params(self, mock_client):
        """The Assignment Groups API takes name/position/group_weight unnested."""
        client, transport = mock_client
        transport.add(json_data={"id": 9, "name": "Labs", "position": 2})
        client.create_assignment_group("Labs", position=2, group_weight=25.0)
        body = transport.requests[0].content.decode()
        assert "name=Labs" in body
        assert "position=2" in body
        assert "group_weight=25.0" in body
        assert "assignment_group%5B" not in body

    def test_delete_assignment_group(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 9})
        client.delete_assignment_group(9)
        req = transport.requests[0]
        assert req.method == "DELETE"
        assert str(req.url).endswith("/courses/1/assignment_groups/9")

    def test_resolve_assignment_group_by_id_or_name(self, mock_client):
        client, transport = mock_client
        transport.add(json_data=[{"id": 9, "name": "Labs", "position": 1}])
        assert client.resolve_assignment_group("labs").id == 9
        transport.add(json_data=[{"id": 9, "name": "Labs", "position": 1}])
        assert client.resolve_assignment_group("9").name == "Labs"
        transport.add(json_data=[{"id": 9, "name": "Labs", "position": 1}])
        with pytest.raises(RuntimeError, match="Assignment group not found: nope"):
            client.resolve_assignment_group("nope")

    def test_create_assignment(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data={
                "id": 88,
                "name": "HW2",
                "points_possible": 20,
                "published": False,
            }
        )
        a = client.create_assignment("HW2", points_possible=20)
        assert a.id == 88
        assert transport.requests[0].method == "POST"

    def test_delete_module(self, mock_client):
        client, transport = mock_client
        transport.add(status=200, json_data={})
        client.delete_module(99)
        assert transport.requests[0].method == "DELETE"

    def test_publish(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 1, "published": True})
        client.publish("modules", 1)
        req = transport.requests[0]
        assert req.method == "PUT"

    def test_resolve_module_by_id(self, mock_client):
        client, transport = mock_client
        transport.add(json_data={"id": 5, "name": "Week 5", "position": 5})
        mod = client.resolve_module("5")
        assert mod.id == 5
        # Should use get_module (direct ID lookup)
        assert "/modules/5" in str(transport.requests[0].url)

    def test_resolve_module_by_name(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": 1, "name": "Week 1", "position": 1},
                {"id": 2, "name": "Week 2", "position": 2},
            ]
        )
        mod = client.resolve_module("week 2")
        assert mod.id == 2

    def test_resolve_module_not_found(self, mock_client):
        client, transport = mock_client
        transport.add(
            json_data=[
                {"id": 1, "name": "Week 1", "position": 1},
            ]
        )
        with pytest.raises(RuntimeError, match="Module not found"):
            client.resolve_module("nonexistent")

    def test_pagination(self, mock_client):
        """Verify pagination via Link header."""
        client, transport = mock_client
        # Page 1 with Link header
        transport.add(
            json_data=[{"id": 1, "name": "M1", "position": 1}],
            headers={
                "link": (
                    "<https://canvas.example.com/api/v1/courses/1"
                    '/modules?page=2&per_page=100>; rel="next"'
                )
            },
        )
        # Page 2 with no next link
        transport.add(
            json_data=[{"id": 2, "name": "M2", "position": 2}],
        )
        modules = client.list_modules()
        assert len(modules) == 2
        assert len(transport.requests) == 2

    def test_context_manager(self, mock_client):
        client, _transport = mock_client
        with client:
            assert not client._http.is_closed
        assert client._http.is_closed

    def test_graphql_post_assignment_grades(self, mock_client):
        """postAssignmentGrades returns a Progress object."""
        client, transport = mock_client
        transport.add(
            json_data={
                "data": {
                    "postAssignmentGrades": {
                        "progress": {"_id": "77", "state": "queued"},
                        "errors": [],
                    }
                }
            }
        )
        p = client.post_assignment_grades(200, graded_only=True)
        assert p is not None
        assert p.id == 77
        assert p.workflow_state == "queued"
        req = transport.requests[0]
        assert req.method == "POST"
        assert "/api/graphql" in str(req.url)

    def test_graphql_post_assignment_grades_no_progress(self, mock_client):
        """postAssignmentGrades returns None when no progress is started."""
        client, transport = mock_client
        transport.add(
            json_data={
                "data": {
                    "postAssignmentGrades": {
                        "progress": None,
                        "errors": [],
                    }
                }
            }
        )
        p = client.post_assignment_grades(200)
        assert p is None

    def test_graphql_post_assignment_grades_error(self, mock_client):
        """postAssignmentGrades raises on validation errors."""
        client, transport = mock_client
        transport.add(
            json_data={
                "data": {
                    "postAssignmentGrades": {
                        "progress": None,
                        "errors": [
                            {"attribute": "assignmentId", "message": "not found"}
                        ],
                    }
                }
            }
        )
        with pytest.raises(RuntimeError, match="postAssignmentGrades failed"):
            client.post_assignment_grades(999)

    def test_graphql_hide_assignment_grades(self, mock_client):
        """hideAssignmentGrades returns a Progress object."""
        client, transport = mock_client
        transport.add(
            json_data={
                "data": {
                    "hideAssignmentGrades": {
                        "progress": {"_id": "88", "state": "queued"},
                        "errors": [],
                    }
                }
            }
        )
        p = client.hide_assignment_grades(200)
        assert p is not None
        assert p.id == 88

    def test_graphql_top_level_error(self, mock_client):
        """GraphQL top-level errors raise RuntimeError."""
        client, transport = mock_client
        transport.add(
            json_data={
                "errors": [{"message": "permission denied"}],
            }
        )
        with pytest.raises(RuntimeError, match="Canvas GraphQL error"):
            client.post_assignment_grades(200)
