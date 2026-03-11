/**
 * Kysely Database interface + domain types.
 * Schema v15 — matches the Python cass SQLite schema exactly.
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
	email: Generated<string>;
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

export interface CanvasStudentsTable {
	canvas_id: number;
	name: string;
	sortable_name: Generated<string>;
	email: Generated<string>;
	login_id: Generated<string>;
	sis_user_id: Generated<string>;
	sis_section_id: Generated<string>;
}

export interface CanvasAssignmentsTable {
	canvas_id: number;
	name: string;
	points_possible: Generated<number>;
	due_at: string | null;
	published: Generated<number>;
	assignment_group: Generated<string>;
	post_manually: Generated<number>;
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
}

export interface CanvasGradesTable {
	canvas_user_id: number;
	canvas_assignment_id: number;
	score: number | null;
	posted_grade: Generated<string>;
	updated_at: number;
}

export interface CanvasAssignmentsSyncedTable {
	canvas_id: number;
	name: string;
	points_possible: Generated<number>;
	due_at: string | null;
	published: Generated<number>;
}

export interface CanvasGradesSyncedTable {
	canvas_user_id: number;
	canvas_assignment_id: number;
	posted_grade: Generated<string>;
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
	canvas_students: CanvasStudentsTable;
	canvas_assignments: CanvasAssignmentsTable;
	canvas_submissions: CanvasSubmissionsTable;
	canvas_grades: CanvasGradesTable;
	_canvas_assignments_synced: CanvasAssignmentsSyncedTable;
	_canvas_grades_synced: CanvasGradesSyncedTable;
	gh_students: GHStudentsTable;
	gh_assignments: GHAssignmentsTable;
	gh_submissions: GHSubmissionsTable;
}

// ─── Convenience aliases ────────────────────────────────────────────

export type TableName = keyof Database;

export type Meta = Selectable<MetaTable>;
export type Student = Selectable<StudentsTable>;
export type Assignment = Selectable<AssignmentsTable>;
export type CanvasStudent = Selectable<CanvasStudentsTable>;
export type CanvasAssignment = Selectable<CanvasAssignmentsTable>;
export type CanvasSubmission = Selectable<CanvasSubmissionsTable>;
export type CanvasGrade = Selectable<CanvasGradesTable>;
export type GHStudent = Selectable<GHStudentsTable>;
export type GHAssignment = Selectable<GHAssignmentsTable>;
export type GHSubmission = Selectable<GHSubmissionsTable>;

export type NewStudent = Insertable<StudentsTable>;
export type NewAssignment = Insertable<AssignmentsTable>;
export type NewCanvasStudent = Insertable<CanvasStudentsTable>;
export type NewCanvasAssignment = Insertable<CanvasAssignmentsTable>;
export type NewCanvasSubmission = Insertable<CanvasSubmissionsTable>;
export type NewCanvasGrade = Insertable<CanvasGradesTable>;
export type NewGHStudent = Insertable<GHStudentsTable>;
export type NewGHAssignment = Insertable<GHAssignmentsTable>;
export type NewGHSubmission = Insertable<GHSubmissionsTable>;

export type StudentUpdate = Updateable<StudentsTable>;
export type CanvasAssignmentUpdate = Updateable<CanvasAssignmentsTable>;
export type CanvasGradeUpdate = Updateable<CanvasGradesTable>;
export type GHStudentUpdate = Updateable<GHStudentsTable>;
