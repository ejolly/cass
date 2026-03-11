/**
 * Canvas roster and submission fetching — transforms API responses to DB rows.
 */
import type { KyInstance } from "ky";
import type { NewCanvasAssignment, NewCanvasSubmission, NewStudent } from "../../db/schema.ts";
import { getPaginated } from "./client.ts";
import {
	CanvasAssignmentGroup,
	CanvasAssignmentResponse,
	CanvasSection,
	CanvasStudentResponse,
	CanvasSubmissionResponse,
	CanvasUser,
} from "./schema.ts";

const SUBMITTED_STATES = new Set(["submitted", "graded", "pending_review"]);

/** Fetch students with section info. Returns [students, sisSectionMap]. */
export async function fetchStudentsWithSections(
	client: KyInstance,
	courseId: number,
): Promise<[NewStudent[], Map<number, string>]> {
	const [rawStudents, rawUsers, rawSections] = await Promise.all([
		getPaginated<unknown>(client, `courses/${courseId}/users`, {
			enrollment_type: "student",
		}).then((items) => items.map((i) => CanvasStudentResponse.parse(i))),

		getPaginated<unknown>(client, `courses/${courseId}/users`, {
			enrollment_type: "student",
			include: "enrollments",
		}).then((items) => items.map((i) => CanvasUser.parse(i))),

		getPaginated<unknown>(client, `courses/${courseId}/sections`).then((items) =>
			items.map((i) => CanvasSection.parse(i)),
		),
	]);

	// Build section map: section_id -> sis_section_id
	const sectionMap = new Map<number, string>();
	for (const s of rawSections) {
		if (s.sis_section_id) sectionMap.set(s.id, s.sis_section_id);
	}

	// Build user -> section_id from enrollments
	const userSectionMap = new Map<number, number>();
	for (const u of rawUsers) {
		const studentEnrollment = u.enrollments.find((e) => e.type === "StudentEnrollment");
		if (studentEnrollment) {
			userSectionMap.set(u.id, studentEnrollment.course_section_id);
		}
	}

	// Build sis_section_id map for each canvas_id
	const sisSectionMap = new Map<number, string>();
	for (const [userId, sectionId] of userSectionMap) {
		const sis = sectionMap.get(sectionId);
		if (sis) sisSectionMap.set(userId, sis);
	}

	const students: NewStudent[] = rawStudents.map((s) => ({
		canvas_id: s.id,
		name: s.name,
		sortable_name: s.sortable_name,
		email: s.email ?? "",
		login_id: s.login_id ?? "",
		sis_user_id: s.sis_user_id ?? "",
		sis_section_id: sisSectionMap.get(s.id) ?? "",
		github_username: null,
	}));

	return [students, sisSectionMap];
}

/** Fetch canvas assignments with group names. Returns [assignments, groupNames]. */
export async function fetchCanvasAssignments(
	client: KyInstance,
	courseId: number,
): Promise<[NewCanvasAssignment[], Map<number, string>]> {
	const [rawAssignments, rawGroups] = await Promise.all([
		getPaginated<unknown>(client, `courses/${courseId}/assignments`).then((items) =>
			items.map((i) => CanvasAssignmentResponse.parse(i)),
		),
		getPaginated<unknown>(client, `courses/${courseId}/assignment_groups`).then((items) =>
			items.map((i) => CanvasAssignmentGroup.parse(i)),
		),
	]);

	const groupNames = new Map<number, string>();
	for (const g of rawGroups) {
		groupNames.set(g.id, g.name);
	}

	const assignments: NewCanvasAssignment[] = rawAssignments.map((a) => ({
		canvas_id: a.id,
		name: a.name,
		points_possible: a.points_possible ?? 0,
		due_at: a.due_at,
		published: a.published ? 1 : 0,
		assignment_group: a.assignment_group_id ? (groupNames.get(a.assignment_group_id) ?? "") : "",
		post_manually: a.post_manually ? 1 : 0,
	}));

	return [assignments, groupNames];
}

/** Fetch submissions for a single assignment. */
export async function fetchCanvasSubmissions(
	client: KyInstance,
	courseId: number,
	canvasAssignmentId: number,
	knownCanvasIds: Set<number>,
): Promise<NewCanvasSubmission[]> {
	const rawSubs = await getPaginated<unknown>(
		client,
		`courses/${courseId}/assignments/${canvasAssignmentId}/submissions`,
	).then((items) => items.map((i) => CanvasSubmissionResponse.parse(i)));

	const now = Date.now() / 1000;
	return rawSubs
		.filter((s) => knownCanvasIds.has(s.user_id))
		.map((s) => ({
			canvas_user_id: s.user_id,
			canvas_assignment_id: canvasAssignmentId,
			submitted: SUBMITTED_STATES.has(s.workflow_state) ? 1 : 0,
			submitted_at: s.submitted_at,
			late: s.late ? 1 : 0,
			lateness_seconds: Math.floor(s.seconds_late),
			score: s.score,
			workflow_state: s.workflow_state,
			fetched_at: now,
			posted_grade: s.grade ?? "",
			grade_updated_at: now,
		}));
}
