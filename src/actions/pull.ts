/**
 * Pull orchestration — fetches from APIs and updates DB.
 */
import type { KyInstance } from "ky";
import type { Kysely } from "kysely";
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
import type {
	Database,
	NewAssignment,
	NewCanvasAssignment,
	NewCanvasStudent,
	NewCanvasSubmission,
	NewGHAssignment,
	NewGHStudent,
	NewStudent,
} from "../db/schema.ts";
import { snapshotCanvasAssignmentsSynced, snapshotCanvasGradesSynced } from "../db/sync.ts";
import type { Config } from "./config.ts";
import { hasCanvas, hasClassroom } from "./config.ts";
import { matchStudents, slugMatch, slugify } from "./matching.ts";

export type PullMode =
	| { mode: "all" }
	| { mode: "students" }
	| { mode: "assignments" }
	| { mode: "submissions" };

type ProgressFn = (step: string, detail: string) => void;

const BATCH_SIZE = 500;

/** Batch upsert rows using Kysely insertInto + onConflict. */
async function batchUpsert<T extends keyof Database>(
	db: Kysely<Database>,
	table: T,
	rows: Array<Record<string, unknown>>,
	conflictColumns: string[],
): Promise<void> {
	for (let i = 0; i < rows.length; i += BATCH_SIZE) {
		const batch = rows.slice(i, i + BATCH_SIZE);
		// Determine update columns (all columns except conflict columns)
		const allCols = Object.keys(batch[0]!);
		const updateCols = allCols.filter((c) => !conflictColumns.includes(c));

		const updateSet: Record<string, unknown> = {};
		for (const col of updateCols) {
			// biome-ignore lint/suspicious/noExplicitAny: dynamic column references require untyped eb
			updateSet[col] = (eb: any) => eb.ref(`excluded.${col}`);
		}

		// biome-ignore lint/suspicious/noExplicitAny: dynamic table name requires untyped cast
		await (db.insertInto(table) as any)
			.values(batch)
			// biome-ignore lint/suspicious/noExplicitAny: dynamic conflict columns require untyped oc
			.onConflict((oc: any) => oc.columns(conflictColumns).doUpdateSet(updateSet))
			.execute();
	}
}

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

		const rows: NewCanvasStudent[] = students.map((s) => ({
			canvas_id: s.canvas_id,
			name: s.name,
			sortable_name: s.sortable_name,
			email: s.email,
			login_id: s.login_id,
			sis_user_id: s.sis_user_id,
			sis_section_id: s.sis_section_id,
		}));
		await batchUpsert(db, "canvas_students", rows, ["canvas_id"]);
		onProgress?.("students", `Saved ${students.length} Canvas students`);
	}

	// GitHub students
	if (hasClassroom(cfg)) {
		onProgress?.("students", "Fetching GitHub students...");
		const ghStudents = await fetchAllStudents(cfg.classroomGhId);
		const ghRows: NewGHStudent[] = studentsToDB(ghStudents).map((s) => ({
			github_username: s.github_username,
			github_id: s.github_id,
			name: s.name,
			email: s.email,
		}));

		await batchUpsert(db, "gh_students", ghRows, ["github_username"]);
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

			// Build reverse lookup: canvasId → ghLogin
			const canvasIdToGhLogin = new Map<number, string>();
			for (const [ghLogin, canvasId] of matched.entries()) {
				canvasIdToGhLogin.set(canvasId, ghLogin);
			}

			// Upsert master students
			const studentRows: NewStudent[] = canvasStudents.map((cs) => ({
				canvas_id: cs.canvas_id,
				github_username: canvasIdToGhLogin.get(cs.canvas_id) ?? null,
				name: cs.name,
				email: cs.email,
			}));
			await batchUpsert(db, "students", studentRows, ["canvas_id"]);
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
	let canvasAssignments: NewCanvasAssignment[] = [];

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

		await batchUpsert(db, "canvas_assignments", canvasAssignments, ["canvas_id"]);
		onProgress?.("assignments", `Saved ${canvasAssignments.length} Canvas assignments`);
	}

	let ghAssignmentRows: ReturnType<typeof assignmentsToDB> = [];
	if (hasClassroom(cfg)) {
		onProgress?.("assignments", "Fetching GitHub assignments...");
		const ghAssignments = await fetchAssignments(cfg.classroomGhId);
		ghAssignmentRows = assignmentsToDB(ghAssignments);

		const ghRows: NewGHAssignment[] = ghAssignmentRows.map((a) => ({
			slug: a.slug,
			gh_id: a.gh_id,
			title: a.title,
			deadline: a.deadline ?? null,
			points_possible: a.points_possible,
			accepted: a.accepted,
			submissions_count: a.submissions_count,
			passing_count: a.passing_count,
			starter_code_repo: a.starter_code_repo,
			submittable_files: a.submittable_files,
		}));
		await batchUpsert(db, "gh_assignments", ghRows, ["slug"]);
		onProgress?.("assignments", `Saved ${ghAssignmentRows.length} GitHub assignments`);
	}

	// Merge into master assignments table
	const masterAssignments: NewAssignment[] = [];

	// Canvas-first: create from canvas assignments
	for (const ca of canvasAssignments) {
		const slug = slugify(ca.name);
		const ghMatch = ghAssignmentRows.find((ga) => slugMatch(ga.slug, slug));
		masterAssignments.push({
			slug,
			title: ca.name,
			gh_assignment_slug: ghMatch?.slug ?? null,
			canvas_assignment_id: ca.canvas_id,
			points_possible: ca.points_possible ?? 0,
			deadline: ca.due_at ?? null,
		});
	}

	// Append GH-only assignments
	const matchedGHSlugs = new Set(
		masterAssignments.map((a) => a.gh_assignment_slug).filter(Boolean),
	);
	for (const ga of ghAssignmentRows) {
		if (!matchedGHSlugs.has(ga.slug)) {
			masterAssignments.push({
				slug: ga.slug,
				title: ga.title,
				gh_assignment_slug: ga.slug,
				canvas_assignment_id: null,
				points_possible: ga.points_possible ?? 1,
				deadline: ga.deadline ?? null,
			});
		}
	}

	await batchUpsert(db, "assignments", masterAssignments, ["slug"]);
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
			const rows: NewCanvasSubmission[] = subs.map((s) => ({
				canvas_user_id: s.canvas_user_id,
				canvas_assignment_id: s.canvas_assignment_id,
				submitted: s.submitted,
				submitted_at: s.submitted_at,
				late: s.late,
				lateness_seconds: s.lateness_seconds,
				score: s.score,
				workflow_state: s.workflow_state,
				fetched_at: s.fetched_at,
			}));
			await batchUpsert(db, "canvas_submissions", rows, ["canvas_user_id", "canvas_assignment_id"]);
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
