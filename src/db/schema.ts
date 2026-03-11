/**
 * Kysely Database interface + domain types.
 * Schema v16 — simplified from v15:
 *   - Merged canvas_grades into canvas_submissions (posted_grade + grade_updated_at)
 *   - Merged canvas_students into students (sortable_name, login_id, sis_user_id, sis_section_id)
 *   - Replaced shadow tables with inline _synced_* columns
 */

import type { Generated, Insertable, Selectable, Updateable } from "kysely";

// ─── Table row types ────────────────────────────────────────────────

export interface MetaTable {
  key: string;
  value: string;
}

export interface StudentsTable {
  canvas_id: number;
  github_username: string | null;
  name: Generated<string>;
  sortable_name: Generated<string>;
  email: Generated<string>;
  login_id: Generated<string>;
  sis_user_id: Generated<string>;
  sis_section_id: Generated<string>;
  excluded: Generated<number>;
}

export interface AssignmentsTable {
  slug: string;
  title: string;
  gh_assignment_slug: string | null;
  canvas_assignment_id: number | null;
  points_possible: Generated<number>;
  deadline: string | null;
}

export interface CanvasAssignmentsTable {
  canvas_id: number;
  name: string;
  points_possible: Generated<number>;
  due_at: string | null;
  published: Generated<number>;
  assignment_group: Generated<string>;
  post_manually: Generated<number>;
  // Inline synced columns (baseline from last pull)
  _synced_name: Generated<string>;
  _synced_points_possible: Generated<number>;
  _synced_due_at: Generated<string | null>;
  _synced_published: Generated<number>;
}

export interface CanvasSubmissionsTable {
  canvas_user_id: number;
  canvas_assignment_id: number;
  submitted: Generated<number>;
  submitted_at: string | null;
  late: Generated<number>;
  lateness_seconds: Generated<number>;
  score: number | null;
  workflow_state: Generated<string>;
  fetched_at: number;
  // Grade fields (merged from canvas_grades)
  posted_grade: Generated<string>;
  grade_updated_at: Generated<number>;
  // Inline synced column (baseline from last pull)
  _synced_posted_grade: Generated<string>;
}

export interface GHStudentsTable {
  github_username: string;
  github_id: Generated<number>;
  name: Generated<string>;
  email: Generated<string>;
  excluded: Generated<number>;
}

export interface GHAssignmentsTable {
  slug: string;
  gh_id: number;
  title: string;
  deadline: string | null;
  points_possible: Generated<number>;
  accepted: Generated<number>;
  submissions_count: Generated<number>;
  passing_count: Generated<number>;
  starter_code_repo: Generated<string>;
  submittable_files: Generated<string>;
}

export interface GHSubmissionsTable {
  github_username: string;
  assignment_slug: string;
  submitted: Generated<number>;
  late: Generated<number>;
  lateness_seconds: Generated<number>;
  repo_name: Generated<string>;
  commits_after_deadline: Generated<number>;
  commit_count: Generated<number>;
  passing: Generated<number>;
  gh_autograder_score: Generated<string>;
  last_commit_at: Generated<string>;
  last_commit_sha: Generated<string>;
  fetched_at: number;
}

// ─── Database interface ─────────────────────────────────────────────

export interface Database {
  meta: MetaTable;
  students: StudentsTable;
  assignments: AssignmentsTable;
  canvas_assignments: CanvasAssignmentsTable;
  canvas_submissions: CanvasSubmissionsTable;
  gh_students: GHStudentsTable;
  gh_assignments: GHAssignmentsTable;
  gh_submissions: GHSubmissionsTable;
}

// ─── Convenience aliases ────────────────────────────────────────────

export type TableName = keyof Database;

export type Meta = Selectable<MetaTable>;
export type Student = Selectable<StudentsTable>;
export type Assignment = Selectable<AssignmentsTable>;
export type CanvasAssignment = Selectable<CanvasAssignmentsTable>;
export type CanvasSubmission = Selectable<CanvasSubmissionsTable>;
export type GHStudent = Selectable<GHStudentsTable>;
export type GHAssignment = Selectable<GHAssignmentsTable>;
export type GHSubmission = Selectable<GHSubmissionsTable>;

export type NewStudent = Insertable<StudentsTable>;
export type NewAssignment = Insertable<AssignmentsTable>;
export type NewCanvasAssignment = Insertable<CanvasAssignmentsTable>;
export type NewCanvasSubmission = Insertable<CanvasSubmissionsTable>;
export type NewGHStudent = Insertable<GHStudentsTable>;
export type NewGHAssignment = Insertable<GHAssignmentsTable>;
export type NewGHSubmission = Insertable<GHSubmissionsTable>;

export type StudentUpdate = Updateable<StudentsTable>;
export type CanvasAssignmentUpdate = Updateable<CanvasAssignmentsTable>;
export type CanvasSubmissionUpdate = Updateable<CanvasSubmissionsTable>;
export type GHStudentUpdate = Updateable<GHStudentsTable>;
