/**
 * Display metadata — table names, column config, sidebar groups.
 * Ported from cass/viewer/config.py.
 */
import type { ViewerTableName } from "@cass/db/catalog.ts"

// ─── Display names ───────────────────────────────────────────────────

const DISPLAY_NAMES: Record<ViewerTableName, string> = {
  canvas_submissions: "Submissions",
  canvas_assignments: "Assignments",
  gh_submissions: "Recent Commits",
  gh_students: "Roster",
  gh_assignments: "Assignments",
  students: "Students",
  assignments: "Assignments",
}

export function displayName(table: ViewerTableName): string {
  return DISPLAY_NAMES[table]
}

// ─── Hidden columns ──────────────────────────────────────────────────

const HIDDEN_COLUMNS: Partial<Record<ViewerTableName, string[]>> = {
  canvas_assignments: ["canvas_id"],
  canvas_submissions: ["canvas_user_id", "canvas_assignment_id", "due_at", "late"],
  gh_assignments: ["gh_id", "slug", "starter_code_repo", "submittable_files"],
  gh_students: ["github_id"],
  gh_submissions: ["github_username", "assignment_slug", "last_commit_sha", "commit_url"],
}

// ─── Column ordering ────────────────────────────────────────────────

const COLUMN_ORDERING: Partial<Record<ViewerTableName, string[]>> = {
  canvas_assignments: ["assignment_group", "name", "points_possible", "due_at", "published"],
  canvas_submissions: [
    "student",
    "assignment_name",
    "assignment_group",
    "submitted_at",
    "score",
    "workflow_state",
  ],
  gh_students: ["excluded", "student", "github_username", "email"],
  gh_assignments: [
    "title",
    "points_possible",
    "deadline",
    "accepted",
    "submissions_count",
    "passing_count",
  ],
  gh_submissions: [
    "last_commit_at",
    "student",
    "assignment_name",
    "commit_count",
    "repo_url",
    "late",
  ],
}

// ─── Column display names ───────────────────────────────────────────

const COLUMN_DISPLAY_NAMES: Partial<Record<ViewerTableName, Record<string, string>>> = {
  canvas_assignments: {
    assignment_group: "Group",
    name: "Name",
    points_possible: "Points",
    due_at: "Deadline",
    published: "Published",
  },
  canvas_submissions: {
    student: "Student",
    assignment_name: "Assignment",
    assignment_group: "Group",
    submitted_at: "Submitted",
    score: "Score",
    workflow_state: "State",
  },
  gh_students: {
    excluded: "Hide",
    student: "Student",
    github_username: "GitHub Username",
    email: "Email",
  },
  gh_assignments: {
    title: "Name",
    points_possible: "Points",
    deadline: "Deadline",
    accepted: "Accepted",
    submissions_count: "Submissions",
    passing_count: "Passing",
  },
  gh_submissions: {
    last_commit_at: "Last Commit",
    student: "Student",
    assignment_name: "Assignment",
    commit_count: "Commits",
    repo_url: "Repo",
    late: "Late",
  },
}

// ─── Table groups ───────────────────────────────────────────────────

export interface TableGroup {
  label: string
  tables: ViewerTableName[]
}

export const TABLE_GROUPS: TableGroup[] = [
  {
    label: "Canvas LMS",
    tables: ["canvas_assignments", "canvas_submissions"],
  },
  {
    label: "GitHub Classroom",
    tables: ["gh_submissions", "gh_students", "gh_assignments"],
  },
  {
    label: "Combined",
    tables: ["students", "assignments"],
  },
]

/** Flat list of all viewer tables in sidebar order. */
export const FLAT_TABLES: ViewerTableName[] = TABLE_GROUPS.flatMap((g) => g.tables)

// ─── Helper functions ───────────────────────────────────────────────

/** Get visible columns for a table (filtered + ordered). */
export function getVisibleColumns(table: ViewerTableName, allColumns: string[]): string[] {
  const hidden = new Set(HIDDEN_COLUMNS[table] ?? [])
  const visible = allColumns.filter((c) => !hidden.has(c))
  return orderColumns(table, visible)
}

/** Order columns by preferred ordering, unordered cols go at end. */
function orderColumns(table: ViewerTableName, columns: string[]): string[] {
  const order = COLUMN_ORDERING[table]
  if (!order) return columns

  const rank = new Map(order.map((col, i) => [col, i]))
  return [...columns].sort((a, b) => {
    const ra = rank.get(a) ?? 999
    const rb = rank.get(b) ?? 999
    return ra - rb
  })
}

/** Get display header for a column. */
export function getDisplayHeader(table: ViewerTableName, column: string): string {
  return COLUMN_DISPLAY_NAMES[table]?.[column] ?? column
}
