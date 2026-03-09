"""eGrades CSV export — UCSD final grade submission format.

Generates the 5-column CSV required by UCSD's eGrades system:
``Last Name, First Name, Student ID, SectionId, Final_Assigned_Egrade``

Uses the Canvas enrollments API for ``computed_final_score`` and the
course grading standard to convert percentages to letter grades.
"""

from __future__ import annotations

__docformat__ = "google"

import csv
import logging
from pathlib import Path

from .schema import CanvasGradingSchemeEntry

_log = logging.getLogger(__name__)

EGRADES_HEADER = [
    "Last Name",
    "First Name",
    "Student ID",
    "SectionId",
    "Final_Assigned_Egrade",
]


def score_to_letter(pct: float | None, scheme: list[CanvasGradingSchemeEntry]) -> str:
    """Convert a percentage score to a letter grade using a grading scheme.

    Canvas grading schemes are lists of ``{name, value}`` entries sorted
    descending by ``value``.  Each entry means "scores >= value * 100 earn
    this letter."

    Args:
        pct: Percentage score (0-100), or None for missing.
        scheme: Grading scheme entries (will be sorted internally).

    Returns:
        Letter grade string, or ``""`` if score is None or scheme is empty.
    """
    if pct is None or not scheme:
        return ""
    # Canvas stores thresholds as fractions (0.94 = 94%), sort descending
    entries = sorted(scheme, key=lambda e: e.value, reverse=True)
    frac = pct / 100.0
    for entry in entries:
        if frac >= entry.value:
            return entry.name
    # Below the lowest threshold — return the last entry
    return entries[-1].name


def parse_sortable_name(sortable_name: str) -> tuple[str, str]:
    """Parse Canvas ``sortable_name`` into (last_name, first_name).

    Args:
        sortable_name: Name in "Last, First" format.

    Returns:
        Tuple of (last_name, first_name). Falls back to full string
        as last name if no comma found.
    """
    if "," in sortable_name:
        last, first = sortable_name.split(",", 1)
        return last.strip(), first.strip()
    return sortable_name.strip(), ""


def generate_egrades(
    output: str | Path = "egrades.csv",
) -> tuple[Path, int, list[str]]:
    """Generate an eGrades CSV file from Canvas data.

    Fetches enrollments with computed_final_score, resolves the active
    grading scheme, and writes the UCSD eGrades format CSV.

    Args:
        output: Output file path.

    Returns:
        Tuple of (path, row_count, warnings).

    Raises:
        RuntimeError: If no grading standard is configured or no students found.
    """
    from ...db import get_db
    from .client import CanvasClient

    path = Path(output)

    with CanvasClient() as client:
        # 1. Get course grading standard
        course = client.get_course()
        if not course.grading_standard_id:
            raise RuntimeError(
                "No grading standard configured for this course. "
                "Set one in Canvas course settings first."
            )

        standards = client.list_grading_standards()
        scheme_entries: list[CanvasGradingSchemeEntry] = []
        for std in standards:
            if std.id == course.grading_standard_id:
                scheme_entries = std.grading_scheme
                break
        if not scheme_entries:
            raise RuntimeError(
                f"Grading standard {course.grading_standard_id} not found "
                f"in course standards."
            )

        # 2. Get enrollments with final scores
        enrollments = client.list_enrollments()

    # 3. Build student info from DB (sis_user_id, sis_section_id, sortable_name)
    conn = get_db()
    student_rows = conn.execute(
        "SELECT canvas_id, sortable_name, sis_user_id, sis_section_id "
        "FROM canvas_students WHERE sis_user_id != ''"
    ).fetchall()
    student_map = {
        r[0]: {"sortable_name": r[1], "sis_user_id": r[2], "sis_section_id": r[3]}
        for r in student_rows
    }

    # 4. Match enrollments to students and compute grades
    rows: list[list[str]] = []
    warnings: list[str] = []
    for enr in enrollments:
        info = student_map.get(enr.user_id)
        if not info:
            _log.debug("Skipping enrollment %s — no canvas_students match", enr.user_id)
            continue

        if not info["sis_user_id"]:
            warnings.append(f"Student {enr.user_id} missing sis_user_id, skipping")
            continue

        last, first = parse_sortable_name(info["sortable_name"])
        letter = score_to_letter(enr.computed_final_score, scheme_entries)

        if not letter:
            warnings.append(
                f"Student {info['sis_user_id']} ({last}, {first}) "
                f"has no final score, skipping"
            )
            continue

        rows.append(
            [
                last,
                first,
                info["sis_user_id"],
                info["sis_section_id"],
                letter,
            ]
        )

    if not rows:
        raise RuntimeError("No students with valid grades to export.")

    # Sort by last name, first name
    rows.sort(key=lambda r: (r[0].lower(), r[1].lower()))

    # 5. Write CSV
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(EGRADES_HEADER)
        writer.writerows(rows)

    return path, len(rows), warnings
