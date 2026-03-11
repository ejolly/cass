/**
 * Canvas API Zod schemas — each definition = runtime validator + static type + transforms.
 */
import { z } from "zod";

// ─── Course ─────────────────────────────────────────────────────────

export const CanvasCourse = z.object({
	id: z.number(),
	name: z.string(),
	course_code: z.string(),
	workflow_state: z.string(),
	default_view: z.string().optional(),
	enrollment_term_id: z.number().optional(),
	total_students: z.number().optional(),
	time_zone: z.string().optional(),
	grading_standard_id: z.number().nullable().optional(),
});
export type CanvasCourse = z.infer<typeof CanvasCourse>;

// ─── Users & Enrollments ────────────────────────────────────────────

export const CanvasStudentResponse = z.object({
	id: z.number(),
	name: z.string(),
	sortable_name: z.string().default(""),
	email: z.string().nullable().default(null),
	sis_user_id: z.string().nullable().default(null),
	login_id: z.string().nullable().default(null),
});
export type CanvasStudentResponse = z.infer<typeof CanvasStudentResponse>;

export const CanvasEnrollmentGrades = z.object({
	current_score: z.number().nullable().optional(),
	final_score: z.number().nullable().optional(),
	current_grade: z.string().nullable().optional(),
	final_grade: z.string().nullable().optional(),
});
export type CanvasEnrollmentGrades = z.infer<typeof CanvasEnrollmentGrades>;

export const CanvasEnrollment = z.object({
	id: z.number(),
	user_id: z.number(),
	type: z.string(),
	enrollment_state: z.string(),
	role: z.string().default(""),
	course_section_id: z.number(),
	grades: CanvasEnrollmentGrades.optional(),
});
export type CanvasEnrollment = z.infer<typeof CanvasEnrollment>;

export const CanvasUser = z.object({
	id: z.number(),
	name: z.string(),
	sortable_name: z.string().default(""),
	email: z.string().nullable().default(null),
	sis_user_id: z.string().nullable().default(null),
	login_id: z.string().nullable().default(null),
	enrollments: z.array(CanvasEnrollment).default([]),
});
export type CanvasUser = z.infer<typeof CanvasUser>;

// ─── Sections ───────────────────────────────────────────────────────

export const CanvasSection = z.object({
	id: z.number(),
	name: z.string(),
	sis_section_id: z.string().nullable().default(null),
});
export type CanvasSection = z.infer<typeof CanvasSection>;

// ─── Grading Standards ──────────────────────────────────────────────

export const CanvasGradingSchemeEntry = z.object({
	name: z.string(),
	value: z.number(),
});
export type CanvasGradingSchemeEntry = z.infer<typeof CanvasGradingSchemeEntry>;

export const CanvasGradingStandard = z.object({
	id: z.number(),
	title: z.string(),
	grading_scheme: z.array(CanvasGradingSchemeEntry),
});
export type CanvasGradingStandard = z.infer<typeof CanvasGradingStandard>;

// ─── Modules ────────────────────────────────────────────────────────

export const CanvasModuleItem = z.object({
	id: z.number(),
	title: z.string(),
	type: z.string(),
	content_id: z.number().optional(),
	position: z.number(),
	published: z.boolean().default(false),
	html_url: z.string().default(""),
	module_id: z.number(),
});
export type CanvasModuleItem = z.infer<typeof CanvasModuleItem>;

export const CanvasModule = z.object({
	id: z.number(),
	name: z.string(),
	position: z.number(),
	published: z.boolean().default(false),
	items_count: z.number().default(0),
	items_url: z.string().default(""),
});
export type CanvasModule = z.infer<typeof CanvasModule>;

// ─── Assignments & Groups ───────────────────────────────────────────

export const CanvasAssignmentResponse = z.object({
	id: z.number(),
	name: z.string(),
	points_possible: z.number().nullable().default(null),
	due_at: z.string().nullable().default(null),
	published: z.boolean().default(false),
	submission_types: z.array(z.string()).default([]),
	grading_type: z.string().default(""),
	assignment_group_id: z.number().optional(),
	position: z.number().nullable().optional(),
	html_url: z.string().default(""),
	description: z.string().nullable().default(null),
	lock_at: z.string().nullable().default(null),
	unlock_at: z.string().nullable().default(null),
	has_submitted_submissions: z.boolean().default(false),
	workflow_state: z.string().default(""),
	post_manually: z.boolean().default(false),
});
export type CanvasAssignmentResponse = z.infer<typeof CanvasAssignmentResponse>;

export const CanvasAssignmentGroup = z.object({
	id: z.number(),
	name: z.string(),
	position: z.number().default(0),
	group_weight: z.number().default(0),
	rules: z.record(z.unknown()).default({}),
});
export type CanvasAssignmentGroup = z.infer<typeof CanvasAssignmentGroup>;

// ─── Quizzes ────────────────────────────────────────────────────────

export const CanvasQuiz = z.object({
	id: z.number(),
	title: z.string(),
	quiz_type: z.string().default(""),
	published: z.boolean().default(false),
	time_limit: z.number().nullable().default(null),
	question_count: z.number().default(0),
	points_possible: z.number().nullable().default(null),
	assignment_id: z.number().nullable().default(null),
	html_url: z.string().default(""),
	description: z.string().nullable().default(null),
});
export type CanvasQuiz = z.infer<typeof CanvasQuiz>;

// ─── Files & Folders ────────────────────────────────────────────────

export const CanvasFile = z
	.object({
		id: z.number(),
		display_name: z.string(),
		filename: z.string().default(""),
		size: z.number().default(0),
		"content-type": z.string().default(""),
		url: z.string().default(""),
		folder_id: z.number().optional(),
		created_at: z.string().default(""),
		updated_at: z.string().default(""),
	})
	.transform(({ "content-type": contentType, ...rest }) => ({
		...rest,
		contentType,
	}));
export type CanvasFile = z.infer<typeof CanvasFile>;

export const CanvasFolder = z.object({
	id: z.number(),
	name: z.string(),
	full_name: z.string().default(""),
	parent_folder_id: z.number().nullable().default(null),
	files_count: z.number().default(0),
	folders_count: z.number().default(0),
	position: z.number().nullable().default(null),
});
export type CanvasFolder = z.infer<typeof CanvasFolder>;

// ─── Announcements ──────────────────────────────────────────────────

export const CanvasAnnouncement = z.object({
	id: z.number(),
	title: z.string(),
	message: z.string().default(""),
	posted_at: z.string().nullable().default(null),
	user_name: z.string().default(""),
});
export type CanvasAnnouncement = z.infer<typeof CanvasAnnouncement>;

// ─── Tabs ───────────────────────────────────────────────────────────

export const CanvasTab = z.object({
	id: z.string(), // tab IDs are strings, not ints
	label: z.string(),
	type: z.string().default(""),
	position: z.number().default(0),
	visibility: z.string().default(""),
	hidden: z.boolean().default(false),
});
export type CanvasTab = z.infer<typeof CanvasTab>;

// ─── Submissions ────────────────────────────────────────────────────

export const CanvasSubmissionResponse = z.object({
	user_id: z.number(),
	submitted_at: z.string().nullable().default(null),
	late: z.boolean().default(false),
	missing: z.boolean().default(false),
	seconds_late: z.number().default(0),
	grade: z.string().nullable().default(null),
	score: z.number().nullable().default(null),
	workflow_state: z.string().default(""),
});
export type CanvasSubmissionResponse = z.infer<typeof CanvasSubmissionResponse>;

// ─── Async Progress ─────────────────────────────────────────────────

export const CanvasProgressState = z.enum(["queued", "running", "completed", "failed"]);
export type CanvasProgressState = z.infer<typeof CanvasProgressState>;

export const CanvasProgress = z.object({
	id: z.number(),
	workflow_state: CanvasProgressState,
	completion: z.number().nullable().default(null),
	message: z.string().nullable().default(null),
	tag: z.string().default(""),
	url: z.string().default(""),
});
export type CanvasProgress = z.infer<typeof CanvasProgress>;
