"""Shared view builders for CLI and viewer parity."""

from __future__ import annotations

__docformat__ = "google"

import msgspec
import sqlite_utils


def _format_grade_value(value: object) -> str:
    """Format a grade-like value for gradebook display."""
    if value is None:
        return ""
    if isinstance(value, int | float):
        return f"{value:g}"
    return str(value)


class CanvasGradebookAssignment(msgspec.Struct):
    canvas_id: int
    name: str
    points_possible: float
    published: bool
    assignment_group: str


class CanvasGradebookStudent(msgspec.Struct):
    canvas_id: int
    sortable_name: str


class CanvasGradebookData(msgspec.Struct):
    assignments: list[CanvasGradebookAssignment]
    students: list[CanvasGradebookStudent]
    grades: dict[tuple[int, int], str]


def load_canvas_gradebook_data(conn: sqlite_utils.Database) -> CanvasGradebookData:
    """Load shared Canvas gradebook data for both CLI and viewer."""
    assignments = [
        CanvasGradebookAssignment(
            canvas_id=int(row[0]),
            name=str(row[1]),
            points_possible=float(row[2]),
            published=bool(row[3]),
            assignment_group=str(row[4] or ""),
        )
        for row in conn.execute(
            "SELECT canvas_id, name, points_possible, published, assignment_group "
            "FROM canvas_assignments ORDER BY assignment_group, name"
        ).fetchall()
    ]
    students = [
        CanvasGradebookStudent(canvas_id=int(row[0]), sortable_name=str(row[1]))
        for row in conn.execute(
            "SELECT canvas_id, sortable_name FROM canvas_students "
            "ORDER BY sortable_name"
        ).fetchall()
    ]
    # Start from submission scores so the gradebook remains populated even when
    # the local working copy table has not been edited yet.
    grades = {
        (int(row[0]), int(row[1])): _format_grade_value(row[2])
        for row in conn.execute(
            "SELECT canvas_user_id, canvas_assignment_id, score "
            "FROM canvas_submissions "
            "WHERE score IS NOT NULL"
        ).fetchall()
    }
    # Local grade edits override submission scores. Prefer posted_grade when
    # present, otherwise fall back to the stored numeric score.
    for row in conn.execute(
        "SELECT canvas_user_id, canvas_assignment_id, score, posted_grade "
        "FROM canvas_grades"
    ).fetchall():
        key = (int(row[0]), int(row[1]))
        posted_grade = str(row[3] or "")
        grades[key] = posted_grade or _format_grade_value(row[2])
    return CanvasGradebookData(
        assignments=assignments, students=students, grades=grades
    )


def build_canvas_gradebook_matrix(
    conn: sqlite_utils.Database,
) -> tuple[list[str], list[list[str]]]:
    """Build a gradebook matrix for CLI/report output."""
    data = load_canvas_gradebook_data(conn)
    headers = ["Student", *[assignment.name for assignment in data.assignments]]
    rows: list[list[str]] = []
    for student in data.students:
        row = [student.sortable_name]
        for assignment in data.assignments:
            row.append(data.grades.get((student.canvas_id, assignment.canvas_id), "-"))
        rows.append(row)
    return headers, rows
