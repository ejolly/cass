import type { KyInstance } from "ky";
/**
 * Pull orchestration — fetches from APIs and updates DB.
 */
import type { Kysely } from "kysely";
import { sql } from "kysely";
import {
	fetchCanvasAssignments,
	fetchCanvasSubmissions,
	fetchStudentsWithSections,
} from "../apis/canvas/matching.ts";
import {
	assignmentsToDB,
	fetchAllStudents,
	fetchAssignments,
	studentsToDB,
} from "../apis/github/classroom.ts";
import type { Database } from "../db/schema.ts";
import { snapshotCanvasAssignmentsSynced, snapshotCanvasGradesSynced } from "../db/sync.ts";
import type { Config } from "./config.ts";
import { hasCanvas, hasClassroom } from "./config.ts";
import { matchStudents } from "./matching.ts";
import { slugMatch, slugify } from "./matching.ts";

export type PullMode =
	| { mode: "all" }
	| { mode: "students" }
	| { mode: "assignments" }
	| { mode: "submissions" };

type ProgressFn = (step: string, detail: string) => void;

/** Pull students from Canvas + GitHub, match, and save to DB. */
export async function pullStudents(
	db: Kysely<Database>,
	canvasClient: KyInstance | null,
	cfg: Config,
	onProgress?: ProgressFn,
): Promise<void> {
	// Canvas students
	if (canvasClient && hasCanvas(cfg)) {
		onProgress?.("students", "Fetching Canvas students...");
		const [students] = await fetchStudentsWithSections(canvasClient, cfg.canvasCourseId);

		// Upsert canvas_students
		for (const s of students) {
			await sql`INSERT OR REPLACE INTO canvas_students (canvas_id, name, sortable_name, email, login_id, sis_user_id, sis_section_id)
				VALUES (${s.canvas_id}, ${s.name}, ${s.sortable_name}, ${s.email}, ${s.login_id}, ${s.sis_user_id}, ${s.sis_section_id})`.execute(
				db,
			);
		}
		onProgress?.("students", `Saved ${students.length} Canvas students`);
	}

	// GitHub students
	if (hasClassroom(cfg)) {
		onProgress?.("students", "Fetching GitHub students...");
		const ghStudents = await fetchAllStudents(cfg.classroomGhId);
		const ghRows = studentsToDB(ghStudents);

		for (const s of ghRows) {
			await sql`INSERT OR REPLACE INTO gh_students (github_username, github_id, name, email)
				VALUES (${s.github_username}, ${s.github_id}, ${s.name}, ${s.email})`.execute(db);
		}
		onProgress?.("students", `Saved ${ghRows.length} GitHub students`);

		// Auto-match
		if (canvasClient && hasCanvas(cfg)) {
			const canvasStudents = await db.selectFrom("canvas_students").selectAll().execute();
			const { matched } = matchStudents(
				ghStudents,
				canvasStudents.map((s) => ({
					id: s.canvas_id,
					name: s.name,
					sortable_name: s.sortable_name,
					email: s.email,
					sis_user_id: s.sis_user_id,
					login_id: s.login_id,
				})),
			);

			// Upsert master students
			for (const cs of canvasStudents) {
				const ghLogin = [...matched.entries()].find(([, cid]) => cid === cs.canvas_id)?.[0] ?? null;
				await sql`INSERT OR REPLACE INTO students (canvas_id, github_username, name, email)
					VALUES (${cs.canvas_id}, ${ghLogin}, ${cs.name}, ${cs.email})`.execute(db);
			}
			onProgress?.("students", `Matched ${matched.size} students`);
		}
	}
}

/** Pull assignments from Canvas + GitHub and merge into master table. */
export async function pullAssignments(
	db: Kysely<Database>,
	canvasClient: KyInstance | null,
	cfg: Config,
	onProgress?: ProgressFn,
): Promise<void> {
	let canvasAssignments: Array<{
		canvas_id: number;
		name: string;
		points_possible: number;
		due_at: string | null;
		published: number;
		assignment_group: string;
		post_manually: number;
	}> = [];

	if (canvasClient && hasCanvas(cfg)) {
		onProgress?.("assignments", "Fetching Canvas assignments...");
		const [assignments] = await fetchCanvasAssignments(canvasClient, cfg.canvasCourseId);
		canvasAssignments = assignments.map((a) => ({
			canvas_id: a.canvas_id,
			name: a.name,
			points_possible: a.points_possible ?? 0,
			due_at: a.due_at ?? null,
			published: a.published ?? 0,
			assignment_group: a.assignment_group ?? "",
			post_manually: a.post_manually ?? 0,
		}));

		for (const a of canvasAssignments) {
			await sql`INSERT OR REPLACE INTO canvas_assignments (canvas_id, name, points_possible, due_at, published, assignment_group, post_manually)
				VALUES (${a.canvas_id}, ${a.name}, ${a.points_possible}, ${a.due_at}, ${a.published}, ${a.assignment_group}, ${a.post_manually})`.execute(
				db,
			);
		}
		onProgress?.("assignments", `Saved ${canvasAssignments.length} Canvas assignments`);
	}

	let ghAssignmentRows: ReturnType<typeof assignmentsToDB> = [];
	if (hasClassroom(cfg)) {
		onProgress?.("assignments", "Fetching GitHub assignments...");
		const ghAssignments = await fetchAssignments(cfg.classroomGhId);
		ghAssignmentRows = assignmentsToDB(ghAssignments);

		for (const a of ghAssignmentRows) {
			await sql`INSERT OR REPLACE INTO gh_assignments (slug, gh_id, title, deadline, points_possible, accepted, submissions_count, passing_count, starter_code_repo, submittable_files)
				VALUES (${a.slug}, ${a.gh_id}, ${a.title}, ${a.deadline ?? null}, ${a.points_possible}, ${a.accepted}, ${a.submissions_count}, ${a.passing_count}, ${a.starter_code_repo}, ${a.submittable_files})`.execute(
				db,
			);
		}
		onProgress?.("assignments", `Saved ${ghAssignmentRows.length} GitHub assignments`);
	}

	// Merge into master assignments table
	const masterAssignments: Array<{
		slug: string;
		title: string;
		ghSlug: string | null;
		canvasId: number | null;
		points: number;
		deadline: string | null;
	}> = [];

	// Canvas-first: create from canvas assignments
	for (const ca of canvasAssignments) {
		const slug = slugify(ca.name);
		const ghMatch = ghAssignmentRows.find((ga) => slugMatch(ga.slug, slug));
		masterAssignments.push({
			slug,
			title: ca.name,
			ghSlug: ghMatch?.slug ?? null,
			canvasId: ca.canvas_id,
			points: ca.points_possible,
			deadline: ca.due_at,
		});
	}

	// Append GH-only assignments
	const matchedGHSlugs = new Set(masterAssignments.map((a) => a.ghSlug).filter(Boolean));
	for (const ga of ghAssignmentRows) {
		if (!matchedGHSlugs.has(ga.slug)) {
			masterAssignments.push({
				slug: ga.slug,
				title: ga.title,
				ghSlug: ga.slug,
				canvasId: null,
				points: ga.points_possible ?? 1,
				deadline: ga.deadline ?? null,
			});
		}
	}

	for (const a of masterAssignments) {
		await sql`INSERT OR REPLACE INTO assignments (slug, title, gh_assignment_slug, canvas_assignment_id, points_possible, deadline)
			VALUES (${a.slug}, ${a.title}, ${a.ghSlug}, ${a.canvasId}, ${a.points}, ${a.deadline})`.execute(
			db,
		);
	}
	onProgress?.("assignments", `Merged ${masterAssignments.length} master assignments`);
}

/** Pull submissions from Canvas + GitHub. */
export async function pullSubmissions(
	db: Kysely<Database>,
	canvasClient: KyInstance | null,
	cfg: Config,
	onProgress?: ProgressFn,
): Promise<void> {
	// Canvas submissions
	if (canvasClient && hasCanvas(cfg)) {
		const assignments = await db.selectFrom("canvas_assignments").select("canvas_id").execute();
		const knownIds = await db.selectFrom("canvas_students").select("canvas_id").execute();
		const knownSet = new Set(knownIds.map((r) => r.canvas_id));

		for (const a of assignments) {
			onProgress?.("submissions", `Fetching Canvas submissions for assignment ${a.canvas_id}...`);
			const subs = await fetchCanvasSubmissions(
				canvasClient,
				cfg.canvasCourseId,
				a.canvas_id,
				knownSet,
			);
			for (const s of subs) {
				await sql`INSERT OR REPLACE INTO canvas_submissions (canvas_user_id, canvas_assignment_id, submitted, submitted_at, late, lateness_seconds, score, workflow_state, fetched_at)
					VALUES (${s.canvas_user_id}, ${s.canvas_assignment_id}, ${s.submitted}, ${s.submitted_at}, ${s.late}, ${s.lateness_seconds}, ${s.score}, ${s.workflow_state}, ${s.fetched_at})`.execute(
					db,
				);
			}
		}
		onProgress?.("submissions", `Saved Canvas submissions for ${assignments.length} assignments`);
	}

	onProgress?.("submissions", "Done");
}

/** Full pull — non-interactive, runs all steps. */
export async function pullAll(
	db: Kysely<Database>,
	canvasClient: KyInstance | null,
	cfg: Config,
	onProgress?: ProgressFn,
): Promise<void> {
	await pullStudents(db, canvasClient, cfg, onProgress);
	await pullAssignments(db, canvasClient, cfg, onProgress);
	await pullSubmissions(db, canvasClient, cfg, onProgress);

	// Snapshot synced state
	await snapshotCanvasGradesSynced(db);
	await snapshotCanvasAssignmentsSynced(db);
	onProgress?.("sync", "Synced shadow tables");
}
