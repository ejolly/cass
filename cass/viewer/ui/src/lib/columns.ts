/** Column display configuration: hidden columns, ordering, width estimation. */

/** Columns to hide for specific tables (internal IDs that clutter the view). */
const HIDDEN_COLUMNS: Record<string, string[]> = {
  canvas_assignments: ["canvas_id"],
  canvas_students: ["canvas_id"],
  canvas_submissions: ["canvas_user_id", "canvas_assignment_id"],
  canvas_grades: ["canvas_user_id", "canvas_assignment_id"],
};

/** Preferred column order for specific tables. */
const COLUMN_ORDERING: Record<string, string[]> = {
  canvas_assignments: [
    "assignment_group",
    "name",
    "points_possible",
    "due_at",
    "published",
  ],
  canvas_submissions: [
    "student_name",
    "assignment_name",
    "assignment_group",
    "submitted",
    "submitted_at",
    "late",
    "score",
    "workflow_state",
  ],
  canvas_grades: [
    "student_name",
    "assignment_name",
    "assignment_group",
    "score",
    "posted_grade",
    "updated_at",
  ],
};

/** Get visible columns in display order for a table. */
export function getDisplayedColumns(
  tableName: string,
  allCols: string[],
): string[] {
  const hidden = HIDDEN_COLUMNS[tableName] ?? [];
  const visible = allCols.filter((c) => !hidden.includes(c));

  const ordering = COLUMN_ORDERING[tableName];
  if (!ordering) return visible;

  const ordered = ordering.filter((c) => visible.includes(c));
  const remaining = visible.filter((c) => !ordering.includes(c));
  return [...ordered, ...remaining];
}

/** Estimate pixel width for a column based on name and type. */
export function estimateColumnWidth(colName: string, colType: string): number {
  const base = colName.length * 9 + 40;
  if (colType.includes("TIMESTAMP")) {
    return Math.max(180, base);
  }
  return Math.max(90, base);
}
