"""Canvas LMS integration — httpx client, roster matching, grade sync."""

from __future__ import annotations

import os
import re
from datetime import datetime

import httpx
import msgspec

from .config import get_config
from .models import Assignment, GHStudentInfo, Student, Submission


# --- Canvas API response types ---


class CanvasStudent(msgspec.Struct):
    id: int
    name: str
    sortable_name: str = ""
    email: str = ""


class CanvasAssignment(msgspec.Struct):
    id: int
    name: str
    points_possible: float = 0.0
    due_at: str | None = None


class CanvasSubmission(msgspec.Struct):
    user_id: int
    submitted_at: str | None = None
    late: bool = False
    missing: bool = False
    seconds_late: float = 0.0
    grade: str | None = None
    score: float | None = None
    workflow_state: str = ""


class MatchResult(msgspec.Struct):
    matched: dict[str, int]  # gh_login -> canvas_id
    unmatched_gh: list[GHStudentInfo]
    unmatched_canvas: list[CanvasStudent]


# --- Token management ---


def get_token() -> str:
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
    cfg = get_config()
    token_path = cfg.root / "canvas-token.txt"
    token_path.write_text(token.strip() + "\n")


# --- HTTP client ---


def _client() -> httpx.Client:
    cfg = get_config()
    base_url = cfg.canvas_base_url.rstrip("/") + "/api/v1"
    token = get_token()
    return httpx.Client(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "cass-cli/0.2",
        },
        timeout=30.0,
    )


_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _get_paginated(client: httpx.Client, path: str) -> list[dict]:
    """GET with Canvas-style Link header pagination."""
    results: list[dict] = []
    sep = "&" if "?" in path else "?"
    url = f"{path}{sep}per_page=100"

    while url:
        resp = client.get(url)
        resp.raise_for_status()
        results.extend(resp.json())

        url = ""
        link = resp.headers.get("link", "")
        if m := _LINK_NEXT_RE.search(link):
            url = m.group(1)
            # Canvas returns full URLs; strip base_url if present
            base = str(client.base_url)
            if url.startswith(base):
                url = url[len(base) :]

    return results


# --- API functions ---


def fetch_students(course_id: int) -> list[CanvasStudent]:
    with _client() as c:
        data = _get_paginated(
            c, f"/courses/{course_id}/users?enrollment_type[]=student&include[]=email"
        )
    decoder = msgspec.json.Decoder(list[CanvasStudent])
    return decoder.decode(msgspec.json.encode(data))


def fetch_assignments(course_id: int) -> list[Assignment]:
    with _client() as c:
        data = _get_paginated(c, f"/courses/{course_id}/assignments")
    raw = msgspec.json.decode(msgspec.json.encode(data), type=list[CanvasAssignment])

    assignments = []
    for a in raw:
        deadline = None
        if a.due_at:
            try:
                deadline = datetime.fromisoformat(a.due_at.replace("Z", "+00:00"))
            except ValueError:
                pass
        assignments.append(
            Assignment(
                id=_slugify(a.name),
                source="canvas",
                title=a.name,
                canvas_id=a.id,
                deadline=deadline,
                points_possible=a.points_possible,
            )
        )
    return sorted(assignments, key=lambda a: a.id)


def fetch_submissions(
    course_id: int,
    assignment_id: int,
    students: list[Student],
) -> list[Submission]:
    with _client() as c:
        data = _get_paginated(
            c, f"/courses/{course_id}/assignments/{assignment_id}/submissions"
        )
    raw = msgspec.json.decode(msgspec.json.encode(data), type=list[CanvasSubmission])

    # canvas_id -> student identifier
    canvas_to_student: dict[int, str] = {}
    for s in students:
        if s.canvas_id:
            try:
                canvas_to_student[int(s.canvas_id)] = s.display_name
            except ValueError:
                pass

    assignment_id_str = _slugify_canvas_id(assignment_id)
    submissions = []
    for r in raw:
        student_id = canvas_to_student.get(r.user_id)
        if not student_id:
            continue

        submitted_at = None
        if r.submitted_at:
            try:
                submitted_at = datetime.fromisoformat(
                    r.submitted_at.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        sub = Submission(
            student_id=student_id,
            assignment_id=assignment_id_str,
            source="canvas",
            submitted=r.workflow_state in ("submitted", "graded", "pending_review"),
            submitted_at=submitted_at,
            late=r.late,
            lateness_seconds=int(r.seconds_late),
            score=r.score,
            workflow_state=r.workflow_state,
        )
        submissions.append(sub)

    return sorted(submissions, key=lambda s: s.student_id)


def push_grade(
    course_id: int, assignment_id: int, student_canvas_id: int, grade: str
) -> None:
    with _client() as c:
        resp = c.put(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions/{student_canvas_id}",
            data={"submission[posted_grade]": grade},
        )
        resp.raise_for_status()


# --- Name matching ---

_NON_ALPHA_RE = re.compile(r"[^a-z\s]")


def _normalize(name: str) -> str:
    name = name.lower().strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    name = _NON_ALPHA_RE.sub("", name)
    return " ".join(sorted(name.split()))


def match_students(
    gh_students: list[GHStudentInfo],
    canvas_students: list[CanvasStudent],
) -> MatchResult:
    canvas_by_name: dict[str, CanvasStudent] = {}
    for cs in canvas_students:
        for field in (cs.name, cs.sortable_name):
            key = _normalize(field)
            if key:
                canvas_by_name[key] = cs

    matched: dict[str, int] = {}
    used_canvas_ids: set[int] = set()
    unmatched_gh: list[GHStudentInfo] = []

    for gh in gh_students:
        if gh.name:
            key = _normalize(gh.name)
            if key in canvas_by_name:
                cs = canvas_by_name[key]
                matched[gh.login] = cs.id
                used_canvas_ids.add(cs.id)
                continue

            gh_tokens = set(key.split())
            if len(gh_tokens) >= 2:
                found = False
                for cname, cs in canvas_by_name.items():
                    if cs.id in used_canvas_ids:
                        continue
                    if gh_tokens.issubset(set(cname.split())):
                        matched[gh.login] = cs.id
                        used_canvas_ids.add(cs.id)
                        found = True
                        break
                if found:
                    continue

        unmatched_gh.append(gh)

    unmatched_canvas = [cs for cs in canvas_students if cs.id not in used_canvas_ids]
    return MatchResult(
        matched=matched,
        unmatched_gh=unmatched_gh,
        unmatched_canvas=unmatched_canvas,
    )


def find_candidates(
    gh_student: GHStudentInfo,
    canvas_pool: list[CanvasStudent],
) -> list[CanvasStudent]:
    gh_name = gh_student.name or gh_student.login
    gh_tokens = set(_normalize(gh_name).split())
    if not gh_tokens:
        return canvas_pool[:5]

    scored = []
    for c in canvas_pool:
        c_tokens = set(_normalize(c.name).split())
        overlap = len(gh_tokens & c_tokens)
        if overlap > 0:
            scored.append((overlap, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def mapping_from_roster(students: list[Student]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for s in students:
        if s.canvas_id and s.github_username:
            try:
                mapping[s.github_username] = int(s.canvas_id)
            except ValueError:
                pass
    return mapping


# --- Helpers ---


def _slugify(name: str) -> str:
    """Convert a Canvas assignment name to a URL-safe identifier."""
    name = name.lower().strip()
    for sep in (" ", "_", "/", "(", ")"):
        name = name.replace(sep, "-")
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip("-")


def _slugify_canvas_id(assignment_id: int) -> str:
    return f"canvas-{assignment_id}"
