"""Canvas LMS API client — typed CRUD for every Canvas resource.

Provides ``CanvasClient``, a typed httpx client with ``course_id`` baked in.
All methods return msgspec.Struct instances, never raw dicts.

Also contains the HTTP transport layer (``_RetryTransport``) and token
management used by the rest of the Canvas integration.
"""

from __future__ import annotations

__docformat__ = "google"

import logging
import os
import re
import time

import httpx
import msgspec
from rich.console import Console

from .. import __version__
from ..config import get_config
from ..models import (
    CanvasAnnouncement,
    CanvasAssignment,
    CanvasAssignmentGroup,
    CanvasCourse,
    CanvasEnrollment,
    CanvasFile,
    CanvasFolder,
    CanvasGradingStandard,
    CanvasModule,
    CanvasModuleItem,
    CanvasProgress,
    CanvasQuiz,
    CanvasSection,
    CanvasStudent,
    CanvasSubmissionResponse,
    CanvasTab,
    CanvasUser,
)

_console = Console(stderr=True)
_log = logging.getLogger(__name__)

# --- Token management ---

MAX_RETRIES = 3
THROTTLE_THRESHOLD = 50.0
THROTTLE_DELAY = 1.0


def get_token() -> str:
    """Read Canvas API token from file or environment.

    Looks for ``canvas-token.txt`` in the project root first, then
    falls back to the ``CANVAS_TOKEN`` environment variable.

    Raises:
        SystemExit: If no token is found.
    """
    cfg = get_config()
    token_path = cfg.root / "canvas-token.txt"
    if token_path.exists():
        token = token_path.read_text().strip()
        if token:
            return token
    token = os.environ.get("CANVAS_TOKEN", "")
    if not token:
        raise SystemExit(
            "Canvas token not found. Create canvas-token.txt in the project root "
            "or set the CANVAS_TOKEN environment variable."
        )
    return token


def save_token(token: str) -> None:
    """Write a Canvas API token to ``canvas-token.txt``."""
    cfg = get_config()
    token_path = cfg.root / "canvas-token.txt"
    token_path.write_text(token.strip() + "\n")


# --- HTTP transport ---


class _RetryTransport(httpx.BaseTransport):
    """Wraps HTTPTransport with 429 retry, backoff, and proactive throttling."""

    def __init__(self, *, retries: int = 0) -> None:
        self._wrapped = httpx.HTTPTransport(retries=retries)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(MAX_RETRIES + 1):
            response = self._wrapped.handle_request(request)

            if response.status_code == 429:
                if attempt == MAX_RETRIES:
                    return response  # let raise_for_status handle it
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else 2**attempt
                _console.print(
                    f"[yellow]Canvas rate limit hit, retrying in {wait:.0f}s…[/yellow]"
                )
                time.sleep(wait)
                continue

            # Proactive throttle when remaining quota is low
            remaining = response.headers.get("X-Rate-Limit-Remaining")
            if remaining:
                try:
                    if float(remaining) < THROTTLE_THRESHOLD:
                        _log.debug(
                            "Rate limit remaining %.1f, throttling", float(remaining)
                        )
                        time.sleep(THROTTLE_DELAY)
                except ValueError:
                    pass

            # Log request cost at debug level
            cost = response.headers.get("X-Request-Cost")
            if cost:
                _log.debug("Request cost: %s", cost)

            return response

        # Should not reach here, but satisfy the type checker
        raise RuntimeError("Canvas API rate limit exceeded after retries")

    def close(self) -> None:
        self._wrapped.close()


# --- Client ---

_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class CanvasClient:
    """Typed Canvas LMS API client with course_id baked in.

    Args:
        base_url: Canvas instance URL (e.g. ``https://canvas.ucsd.edu``).
        token: Canvas API bearer token.
        course_id: Canvas course ID for all requests.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        course_id: int | None = None,
    ) -> None:
        cfg = get_config()
        self._base_url = (base_url or cfg.canvas_base_url).rstrip("/") + "/api/v1"
        self._token = token or get_token()
        self.course_id = course_id or cfg.canvas_course_id
        self._http: httpx.Client | None = None

    @property
    def _client(self) -> httpx.Client:
        if self._http is None or self._http.is_closed:
            self._http = httpx.Client(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "User-Agent": f"cass-cli/{__version__}",
                },
                transport=_RetryTransport(retries=1),
                timeout=30.0,
            )
        return self._http

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http and not self._http.is_closed:
            self._http.close()

    def __enter__(self) -> CanvasClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- Pagination ---

    def _get_paginated(self, path: str) -> list[dict]:
        """GET with Canvas-style Link header pagination."""
        results: list[dict] = []
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}per_page=100"

        while url:
            resp = self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)

            url = ""
            link = resp.headers.get("link", "")
            if m := _LINK_NEXT_RE.search(link):
                url = m.group(1)
                base = str(self._client.base_url)
                if url.startswith(base):
                    url = url[len(base) :]

        return results

    def _course(self, path: str = "") -> str:
        """Build a course-scoped API path."""
        return f"/courses/{self.course_id}{path}"

    # --- Course ---

    def get_course(self) -> CanvasCourse:
        """Get course details.

        Returns:
            Course metadata.
        """
        resp = self._client.get(self._course("?include[]=total_students"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasCourse, strict=False)

    # --- People ---

    def list_users(self, enrollment_type: str | None = None) -> list[CanvasUser]:
        """List course users with enrollments.

        Args:
            enrollment_type: Filter by role (e.g. ``student``, ``teacher``).

        Returns:
            Users sorted by name.
        """
        path = self._course("/users?include[]=enrollments&include[]=email")
        if enrollment_type:
            path += f"&enrollment_type[]={enrollment_type}"
        data = self._get_paginated(path)
        return msgspec.convert(data, list[CanvasUser], strict=False)

    def list_students(self) -> list[CanvasStudent]:
        """List students enrolled in the course.

        Returns:
            Students sorted by Canvas enrollment order.
        """
        data = self._get_paginated(
            self._course("/users?enrollment_type[]=student&include[]=email")
        )
        return msgspec.convert(data, list[CanvasStudent], strict=False)

    # --- Sections ---

    def list_sections(self) -> list[CanvasSection]:
        """List all course sections.

        Returns:
            Sections with SIS IDs (if available).
        """
        data = self._get_paginated(self._course("/sections"))
        return msgspec.convert(data, list[CanvasSection], strict=False)

    # --- Enrollments ---

    def list_enrollments(
        self, *, enrollment_type: str = "StudentEnrollment"
    ) -> list[CanvasEnrollment]:
        """List enrollments with computed scores.

        Args:
            enrollment_type: Filter by type (default: StudentEnrollment).

        Returns:
            Enrollments including computed_final_score.
        """
        data = self._get_paginated(
            self._course(
                f"/enrollments?type[]={enrollment_type}"
                "&state[]=active&include[]=total_scores"
            )
        )
        return msgspec.convert(data, list[CanvasEnrollment], strict=False)

    # --- Grading Standards ---

    def list_grading_standards(self) -> list[CanvasGradingStandard]:
        """List grading standards available for this course.

        Returns:
            Grading standards with scheme entries.
        """
        data = self._get_paginated(self._course("/grading_standards"))
        return msgspec.convert(data, list[CanvasGradingStandard], strict=False)

    # --- Modules ---

    def list_modules(self) -> list[CanvasModule]:
        """List all course modules.

        Returns:
            Modules sorted by position.
        """
        data = self._get_paginated(self._course("/modules"))
        return msgspec.convert(data, list[CanvasModule], strict=False)

    def get_module(self, module_id: int) -> CanvasModule:
        """Get a single module by ID."""
        resp = self._client.get(self._course(f"/modules/{module_id}"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def list_module_items(self, module_id: int) -> list[CanvasModuleItem]:
        """List items in a module.

        Args:
            module_id: Canvas module ID.

        Returns:
            Module items sorted by position.
        """
        data = self._get_paginated(self._course(f"/modules/{module_id}/items"))
        return msgspec.convert(data, list[CanvasModuleItem], strict=False)

    def create_module(self, name: str, position: int | None = None) -> CanvasModule:
        """Create a new module.

        Args:
            name: Module name.
            position: Optional position in the module list.

        Returns:
            The created module.
        """
        params: dict = {"module[name]": name}
        if position is not None:
            params["module[position]"] = position
        resp = self._client.post(self._course("/modules"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def update_module(self, module_id: int, **kwargs: object) -> CanvasModule:
        """Update a module.

        Args:
            module_id: Canvas module ID.
            **kwargs: Fields to update (name, position, published).

        Returns:
            The updated module.
        """
        params = {f"module[{k}]": v for k, v in kwargs.items()}
        resp = self._client.put(self._course(f"/modules/{module_id}"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModule, strict=False)

    def delete_module(self, module_id: int) -> None:
        """Delete a module."""
        resp = self._client.delete(self._course(f"/modules/{module_id}"))
        resp.raise_for_status()

    def create_module_item(
        self,
        module_id: int,
        *,
        title: str,
        item_type: str,
        content_id: int,
    ) -> CanvasModuleItem:
        """Add an item to a module.

        Args:
            module_id: Canvas module ID.
            title: Item title.
            item_type: Item type (Assignment, Quiz, File, etc.).
            content_id: ID of the linked content.

        Returns:
            The created module item.
        """
        params = {
            "module_item[title]": title,
            "module_item[type]": item_type,
            "module_item[content_id]": content_id,
        }
        resp = self._client.post(
            self._course(f"/modules/{module_id}/items"), data=params
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasModuleItem, strict=False)

    # --- Assignments ---

    def list_assignments(self) -> list[CanvasAssignment]:
        """List all course assignments.

        Returns:
            Assignments from all assignment groups.
        """
        data = self._get_paginated(self._course("/assignments"))
        return msgspec.convert(data, list[CanvasAssignment], strict=False)

    def get_assignment(self, assignment_id: int) -> CanvasAssignment:
        """Get a single assignment by ID."""
        resp = self._client.get(self._course(f"/assignments/{assignment_id}"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignment, strict=False)

    def create_assignment(
        self,
        name: str,
        *,
        points_possible: float = 0.0,
        due_at: str | None = None,
        submission_types: list[str] | None = None,
        published: bool = False,
        assignment_group_id: int | None = None,
        description: str | None = None,
        grading_type: str = "points",
    ) -> CanvasAssignment:
        """Create a new assignment.

        Args:
            name: Assignment name.
            points_possible: Total points.
            due_at: Due date in ISO 8601 format.
            submission_types: Allowed submission types.
            published: Whether to publish immediately.
            assignment_group_id: Assignment group to place in.
            description: HTML description.
            grading_type: Grading type (points, letter_grade, etc.).

        Returns:
            The created assignment.
        """
        params: dict = {
            "assignment[name]": name,
            "assignment[points_possible]": points_possible,
            "assignment[published]": published,
            "assignment[grading_type]": grading_type,
        }
        if due_at:
            params["assignment[due_at]"] = due_at
        if submission_types:
            params["assignment[submission_types][]"] = submission_types
        if assignment_group_id:
            params["assignment[assignment_group_id]"] = assignment_group_id
        if description:
            params["assignment[description]"] = description

        resp = self._client.post(self._course("/assignments"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignment, strict=False)

    def update_assignment(
        self, assignment_id: int, **kwargs: object
    ) -> CanvasAssignment:
        """Update an assignment.

        Args:
            assignment_id: Canvas assignment ID.
            **kwargs: Fields to update (name, points_possible, due_at, published, etc.).

        Returns:
            The updated assignment.
        """
        params = {f"assignment[{k}]": v for k, v in kwargs.items()}
        resp = self._client.put(
            self._course(f"/assignments/{assignment_id}"), data=params
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAssignment, strict=False)

    def delete_assignment(self, assignment_id: int) -> None:
        """Delete an assignment."""
        resp = self._client.delete(self._course(f"/assignments/{assignment_id}"))
        resp.raise_for_status()

    # --- Assignment Groups ---

    def list_assignment_groups(self) -> list[CanvasAssignmentGroup]:
        """List assignment groups (grade categories).

        Returns:
            Assignment groups with weights and rules.
        """
        data = self._get_paginated(self._course("/assignment_groups"))
        return msgspec.convert(data, list[CanvasAssignmentGroup], strict=False)

    # --- Submissions ---

    def list_submissions(self, assignment_id: int) -> list[CanvasSubmissionResponse]:
        """List submissions for an assignment.

        Args:
            assignment_id: Canvas assignment ID.

        Returns:
            All submissions for the assignment.
        """
        data = self._get_paginated(
            self._course(f"/assignments/{assignment_id}/submissions")
        )
        return msgspec.convert(data, list[CanvasSubmissionResponse], strict=False)

    def push_grade(
        self, assignment_id: int, student_canvas_id: int, grade: str
    ) -> bool:
        """Push a single grade to Canvas.

        Args:
            assignment_id: Canvas assignment ID.
            student_canvas_id: Student's Canvas user ID.
            grade: Grade string to post.

        Returns:
            True on success, False on failure.
        """
        try:
            resp = self._client.put(
                self._course(
                    f"/assignments/{assignment_id}/submissions/{student_canvas_id}"
                ),
                data={"submission[posted_grade]": grade},
            )
            resp.raise_for_status()
            return True
        except (httpx.HTTPStatusError, RuntimeError) as exc:
            _log.warning(
                "Failed to push grade for student %s: %s", student_canvas_id, exc
            )
            return False

    def bulk_push_grades(
        self, assignment_id: int, grade_data: dict[int, str]
    ) -> CanvasProgress:
        """Push grades in bulk for one assignment via the update_grades endpoint.

        Args:
            assignment_id: Canvas assignment ID.
            grade_data: Mapping of student_canvas_id → posted_grade string.

        Returns:
            Progress object for tracking completion.
        """
        params: dict[str, str] = {}
        for student_id, grade in grade_data.items():
            params[f"grade_data[{student_id}][posted_grade]"] = grade
        resp = self._client.post(
            self._course(f"/assignments/{assignment_id}/submissions/update_grades"),
            data=params,
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasProgress, strict=False)

    def check_progress(self, progress_id: int) -> CanvasProgress:
        """Check the status of an async Canvas operation.

        Args:
            progress_id: Progress object ID.

        Returns:
            Current progress state.
        """
        resp = self._client.get(f"/progress/{progress_id}")
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasProgress, strict=False)

    def wait_for_progress(
        self, progress_id: int, *, timeout: float = 120.0
    ) -> CanvasProgress:
        """Poll a progress object until completion or timeout.

        Args:
            progress_id: Progress object ID.
            timeout: Maximum seconds to wait.

        Returns:
            Completed or failed progress object.

        Raises:
            RuntimeError: If the progress times out or fails.
        """
        start = time.time()
        while time.time() - start < timeout:
            p = self.check_progress(progress_id)
            if p.workflow_state == "completed":
                return p
            if p.workflow_state == "failed":
                raise RuntimeError(
                    f"Canvas bulk operation failed: {p.message or 'unknown error'}"
                )
            time.sleep(1.0)
        raise RuntimeError(f"Canvas bulk operation timed out after {timeout:.0f}s")

    # --- GraphQL ---

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a Canvas GraphQL mutation/query.

        Args:
            query: GraphQL query or mutation string.
            variables: Optional variables dict.

        Returns:
            The ``data`` dict from the GraphQL response.

        Raises:
            RuntimeError: If the response contains top-level errors.
        """
        # GraphQL endpoint is at /api/graphql, not under /api/v1
        base = self._base_url.replace("/api/v1", "")
        payload: dict[str, object] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self._client.post(
            f"{base}/api/graphql",
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
            raise RuntimeError(f"Canvas GraphQL error: {msgs}")
        return body.get("data", {})

    _POST_GRADES_MUTATION = """
mutation ($assignmentId: ID!, $gradedOnly: Boolean) {
  postAssignmentGrades(input: {assignmentId: $assignmentId, gradedOnly: $gradedOnly}) {
    progress { _id state }
    errors { attribute message }
  }
}
"""

    _HIDE_GRADES_MUTATION = """
mutation ($assignmentId: ID!) {
  hideAssignmentGrades(input: {assignmentId: $assignmentId}) {
    progress { _id state }
    errors { attribute message }
  }
}
"""

    def post_assignment_grades(
        self, assignment_id: int, *, graded_only: bool = True
    ) -> CanvasProgress | None:
        """Post (reveal) grades to students for a manual-post assignment.

        Uses the Canvas GraphQL ``postAssignmentGrades`` mutation.

        Args:
            assignment_id: Canvas assignment ID.
            graded_only: If True, only post grades for graded submissions.

        Returns:
            Progress object for tracking, or None if no progress was started.

        Raises:
            RuntimeError: If the mutation returns validation errors.
        """
        data = self._graphql(
            self._POST_GRADES_MUTATION,
            {"assignmentId": str(assignment_id), "gradedOnly": graded_only},
        )
        result = data.get("postAssignmentGrades", {})
        errors = result.get("errors") or []
        if errors:
            msgs = "; ".join(f"{e['attribute']}: {e['message']}" for e in errors)
            raise RuntimeError(f"postAssignmentGrades failed: {msgs}")
        progress = result.get("progress")
        if progress and progress.get("_id"):
            return CanvasProgress(
                id=int(progress["_id"]),
                workflow_state=progress.get("state", "queued"),
            )
        return None

    def hide_assignment_grades(self, assignment_id: int) -> CanvasProgress | None:
        """Hide grades from students for a manual-post assignment.

        Uses the Canvas GraphQL ``hideAssignmentGrades`` mutation.

        Args:
            assignment_id: Canvas assignment ID.

        Returns:
            Progress object for tracking, or None if no progress was started.

        Raises:
            RuntimeError: If the mutation returns validation errors.
        """
        data = self._graphql(
            self._HIDE_GRADES_MUTATION,
            {"assignmentId": str(assignment_id)},
        )
        result = data.get("hideAssignmentGrades", {})
        errors = result.get("errors") or []
        if errors:
            msgs = "; ".join(f"{e['attribute']}: {e['message']}" for e in errors)
            raise RuntimeError(f"hideAssignmentGrades failed: {msgs}")
        progress = result.get("progress")
        if progress and progress.get("_id"):
            return CanvasProgress(
                id=int(progress["_id"]),
                workflow_state=progress.get("state", "queued"),
            )
        return None

    # --- Quizzes ---

    def list_quizzes(self) -> list[CanvasQuiz]:
        """List all course quizzes.

        Returns:
            Quizzes of all types.
        """
        data = self._get_paginated(self._course("/quizzes"))
        return msgspec.convert(data, list[CanvasQuiz], strict=False)

    def get_quiz(self, quiz_id: int) -> CanvasQuiz:
        """Get a single quiz by ID."""
        resp = self._client.get(self._course(f"/quizzes/{quiz_id}"))
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasQuiz, strict=False)

    def create_quiz(
        self,
        title: str,
        *,
        quiz_type: str = "assignment",
        points_possible: float | None = None,
        published: bool = False,
        time_limit: int | None = None,
        description: str | None = None,
    ) -> CanvasQuiz:
        """Create a new quiz.

        Args:
            title: Quiz title.
            quiz_type: Quiz type (practice_quiz, assignment, graded_survey, survey).
            points_possible: Total points.
            published: Whether to publish immediately.
            time_limit: Time limit in minutes.
            description: HTML description.

        Returns:
            The created quiz.
        """
        params: dict = {
            "quiz[title]": title,
            "quiz[quiz_type]": quiz_type,
            "quiz[published]": published,
        }
        if points_possible is not None:
            params["quiz[points_possible]"] = points_possible
        if time_limit is not None:
            params["quiz[time_limit]"] = time_limit
        if description:
            params["quiz[description]"] = description

        resp = self._client.post(self._course("/quizzes"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasQuiz, strict=False)

    def update_quiz(self, quiz_id: int, **kwargs: object) -> CanvasQuiz:
        """Update a quiz.

        Args:
            quiz_id: Canvas quiz ID.
            **kwargs: Fields to update (title, published, etc.).

        Returns:
            The updated quiz.
        """
        params = {f"quiz[{k}]": v for k, v in kwargs.items()}
        resp = self._client.put(self._course(f"/quizzes/{quiz_id}"), data=params)
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasQuiz, strict=False)

    def delete_quiz(self, quiz_id: int) -> None:
        """Delete a quiz."""
        resp = self._client.delete(self._course(f"/quizzes/{quiz_id}"))
        resp.raise_for_status()

    # --- Files & Folders ---

    def list_files(self, folder_id: int | None = None) -> list[CanvasFile]:
        """List files in the course or a specific folder.

        Args:
            folder_id: Optional folder ID to scope the listing.

        Returns:
            File metadata sorted by name.
        """
        if folder_id:
            data = self._get_paginated(f"/folders/{folder_id}/files")
        else:
            data = self._get_paginated(self._course("/files"))
        return msgspec.convert(data, list[CanvasFile], strict=False)

    def list_folders(self) -> list[CanvasFolder]:
        """List all folders in the course.

        Returns:
            Folders with hierarchy info.
        """
        data = self._get_paginated(self._course("/folders"))
        return msgspec.convert(data, list[CanvasFolder], strict=False)

    def upload_file(self, local_path: str, *, folder: str = "") -> CanvasFile:
        """Upload a file to the course.

        Uses Canvas's 3-step file upload flow:
        1. Notify Canvas to get an upload URL
        2. POST the file to the upload URL
        3. Confirm the upload

        Args:
            local_path: Path to the local file.
            folder: Destination folder path in Canvas (e.g. ``course files/slides``).

        Returns:
            The uploaded file metadata.
        """
        import os as _os

        filename = _os.path.basename(local_path)
        size = _os.path.getsize(local_path)

        # Step 1: notify Canvas
        params: dict = {
            "name": filename,
            "size": size,
            "parent_folder_path": folder or "/",
        }
        resp = self._client.post(self._course("/files"), data=params)
        resp.raise_for_status()
        upload_info = resp.json()

        # Step 2: POST to upload URL
        upload_url = upload_info["upload_url"]
        upload_params = upload_info.get("upload_params", {})
        with open(local_path, "rb") as f:
            # Upload URL is absolute — use a fresh httpx call
            resp2 = httpx.post(
                upload_url,
                data=upload_params,
                files={"file": (filename, f)},
                timeout=120.0,
            )
        resp2.raise_for_status()

        # Step 3: Canvas may return the file directly or a redirect
        if resp2.status_code == 201:
            return msgspec.convert(resp2.json(), CanvasFile, strict=False)

        # Follow redirect if needed
        location = resp2.headers.get("Location")
        if location:
            resp3 = self._client.get(location)
            resp3.raise_for_status()
            return msgspec.convert(resp3.json(), CanvasFile, strict=False)

        return msgspec.convert(resp2.json(), CanvasFile, strict=False)

    def delete_file(self, file_id: int) -> None:
        """Delete a file."""
        resp = self._client.delete(f"/files/{file_id}")
        resp.raise_for_status()

    # --- Announcements ---

    def list_announcements(self) -> list[CanvasAnnouncement]:
        """List course announcements.

        Returns:
            Announcements sorted by posted_at descending.
        """
        data = self._get_paginated(
            f"/courses/{self.course_id}/discussion_topics"
            "?only_announcements=true&order_by=recent_activity"
        )
        return msgspec.convert(data, list[CanvasAnnouncement], strict=False)

    def create_announcement(self, title: str, message: str) -> CanvasAnnouncement:
        """Create an announcement.

        Args:
            title: Announcement title.
            message: HTML body.

        Returns:
            The created announcement.
        """
        resp = self._client.post(
            self._course("/discussion_topics"),
            data={
                "title": title,
                "message": message,
                "is_announcement": True,
                "published": True,
            },
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAnnouncement, strict=False)

    def update_announcement(
        self, topic_id: int, **kwargs: object
    ) -> CanvasAnnouncement:
        """Update an announcement.

        Args:
            topic_id: Discussion topic ID.
            **kwargs: Fields to update (title, message).

        Returns:
            The updated announcement.
        """
        resp = self._client.put(
            self._course(f"/discussion_topics/{topic_id}"), data=kwargs
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasAnnouncement, strict=False)

    def delete_announcement(self, topic_id: int) -> None:
        """Delete an announcement."""
        resp = self._client.delete(self._course(f"/discussion_topics/{topic_id}"))
        resp.raise_for_status()

    # --- Tabs ---

    def list_tabs(self) -> list[CanvasTab]:
        """List course navigation tabs.

        Returns:
            Tabs with visibility and position.
        """
        data = self._get_paginated(self._course("/tabs"))
        return msgspec.convert(data, list[CanvasTab], strict=False)

    def update_tab(self, tab_id: str, *, hidden: bool) -> CanvasTab:
        """Show or hide a navigation tab.

        Args:
            tab_id: Tab ID string.
            hidden: True to hide, False to show.

        Returns:
            The updated tab.
        """
        resp = self._client.put(
            self._course(f"/tabs/{tab_id}"), data={"hidden": hidden}
        )
        resp.raise_for_status()
        return msgspec.convert(resp.json(), CanvasTab, strict=False)

    # --- Publish/Unpublish helpers ---

    def publish(self, resource: str, resource_id: int) -> None:
        """Publish a resource (module, assignment, or quiz).

        Args:
            resource: Resource type (``modules``, ``assignments``, ``quizzes``).
            resource_id: Canvas resource ID.
        """
        key = _resource_key(resource)
        resp = self._client.put(
            self._course(f"/{resource}/{resource_id}"),
            data={f"{key}[published]": True},
        )
        resp.raise_for_status()

    def unpublish(self, resource: str, resource_id: int) -> None:
        """Unpublish a resource (module, assignment, or quiz).

        Args:
            resource: Resource type (``modules``, ``assignments``, ``quizzes``).
            resource_id: Canvas resource ID.
        """
        key = _resource_key(resource)
        resp = self._client.put(
            self._course(f"/{resource}/{resource_id}"),
            data={f"{key}[published]": False},
        )
        resp.raise_for_status()

    # --- Resolve by name ---

    def resolve_module(self, id_or_name: str) -> CanvasModule:
        """Resolve a module by numeric ID or name.

        Args:
            id_or_name: Numeric Canvas ID or module name (case-insensitive).

        Returns:
            The matched module.

        Raises:
            RuntimeError: If no module matches.
        """
        if id_or_name.isdigit():
            return self.get_module(int(id_or_name))
        modules = self.list_modules()
        name_lower = id_or_name.lower()
        for m in modules:
            if m.name.lower() == name_lower:
                return m
        raise RuntimeError(f"Module not found: {id_or_name}")

    def resolve_assignment(self, id_or_name: str) -> CanvasAssignment:
        """Resolve an assignment by numeric ID or name.

        Args:
            id_or_name: Numeric Canvas ID or assignment name (case-insensitive).

        Returns:
            The matched assignment.

        Raises:
            RuntimeError: If no assignment matches.
        """
        if id_or_name.isdigit():
            return self.get_assignment(int(id_or_name))
        assignments = self.list_assignments()
        name_lower = id_or_name.lower()
        for a in assignments:
            if a.name.lower() == name_lower:
                return a
        raise RuntimeError(f"Assignment not found: {id_or_name}")

    def resolve_quiz(self, id_or_name: str) -> CanvasQuiz:
        """Resolve a quiz by numeric ID or title.

        Args:
            id_or_name: Numeric Canvas ID or quiz title (case-insensitive).

        Returns:
            The matched quiz.

        Raises:
            RuntimeError: If no quiz matches.
        """
        if id_or_name.isdigit():
            return self.get_quiz(int(id_or_name))
        quizzes = self.list_quizzes()
        name_lower = id_or_name.lower()
        for q in quizzes:
            if q.title.lower() == name_lower:
                return q
        raise RuntimeError(f"Quiz not found: {id_or_name}")


def _resource_key(resource: str) -> str:
    """Map a plural resource name to Canvas API parameter key."""
    return {
        "modules": "module",
        "assignments": "assignment",
        "quizzes": "quiz",
    }.get(resource, resource.rstrip("s"))
