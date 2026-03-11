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
	NewCanvasSubmission,
	NewGHAssignment,
	NewGHStudent,
} from "../db/schema.ts";
import { snapshotAssignmentsSynced, snapshotGradesSynced } from "../db/sync.ts";
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
async function batchUpsert(
	db: Kysely<Database>,
	table: keyof Database,
	rows: ReadonlyArray<Record<string, unknown>>,
	conflictColumns: readonly string[],
): Promise<void> {
	for (let i = 0; i < rows.length; i += BATCH_SIZE) {
		const batch = rows.slice(i, i + BATCH_SIZE);
		const allCols = Object.keys(batch[0]!);
		const updateCols = allCols.filter((c) => !conflictColumns.includes(c));

		const updateSet = Object.fromEntries(
			// biome-ignore lint/suspicious/noExplicitAny: dynamic column references require untyped eb
			updateCols.map((col) => [col, (eb: any) => eb.ref(`excluded.${col}`)]),
		);

		// biome-ignore lint/suspicious/noExplicitAny: dynamic table name requires untyped cast
		await (db.insertInto(table) as any)
			.values(batch)
			// biome-ignore lint/suspicious/noExplicitAny: dynamic conflict columns require untyped oc
			.onConflict((oc: any) => oc.columns(conflictColumns).doUpdateSet(updateSet))
			.execute();
	}
}

/** Coerce typed row arrays to Record<string, unknown>[] for dynamic batchUpsert. */
function asRows<T extends Record<string, unknown>>(rows: readonly T[]): Record<string, unknown>[] {
	return rows as Record<string, unknown>[];
}

/** Pull students from Canvas + GitHub, match, and save to DB. */
export async function pullStudents(
	db: Kysely<Database>,
	canvasClient: KyInstance | null,
	cfg: Config,
	onProgress?: ProgressFn,
): Promise<void> {
	// Canvas students → directly into students table (master)
	if (canvasClient && hasCanvas(cfg)) {
		onProgress?.("students", "Fetching Canvas students...");
		const [students] = await fetchStudentsWithSections(canvasClient, cfg.canvasCourseId);

		await batchUpsert(db, "students", asRows(students), ["canvas_id"]);
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

		await batchUpsert(db, "gh_students", asRows(ghRows), ["github_username"]);
		onProgress?.("students", `Saved ${ghRows.length} GitHub students`);

		// Auto-match: update github_username on master students
		if (canvasClient && hasCanvas(cfg)) {
			const masterStudents = await db.selectFrom("students").selectAll().execute();
			const { matched } = matchStudents(
				ghStudents,
				masterStudents.map((s) => ({
					id: s.canvas_id,
					name: s.name,
					sortable_name: s.sortable_name,
					email: s.email,
					sis_user_id: s.sis_user_id,
					login_id: s.login_id,
				})),
			);

			// Update github_username on matched students
			for (const [ghLogin, canvasId] of matched.entries()) {
				await db
					.updateTable("students")
					.set({ github_username: ghLogin })
					.where("canvas_id", "=", canvasId)
					.execute();
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

		await batchUpsert(db, "canvas_assignments", asRows(canvasAssignments), ["canvas_id"]);
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
		await batchUpsert(db, "gh_assignments", asRows(ghRows), ["slug"]);
		onProgress?.("assignments", `Saved ${ghAssignmentRows.length} GitHub assignments`);
	}

	// Merge into master assignments: Canvas-first, then GH-only
	const canvasToMaster = canvasAssignments.map((ca): NewAssignment => {
		const slug = slugify(ca.name);
		const ghMatch = ghAssignmentRows.find((ga) => slugMatch(ga.slug, slug));
		return {
			slug,
			title: ca.name,
			gh_assignment_slug: ghMatch?.slug ?? null,
			canvas_assignment_id: ca.canvas_id,
			points_possible: ca.points_possible ?? 0,
			deadline: ca.due_at ?? null,
		};
	});

	const matchedGHSlugs = new Set(canvasToMaster.map((a) => a.gh_assignment_slug).filter(Boolean));

	const ghOnlyMaster = ghAssignmentRows
		.filter((ga) => !matchedGHSlugs.has(ga.slug))
		.map(
			(ga): NewAssignment => ({
				slug: ga.slug,
				title: ga.title,
				gh_assignment_slug: ga.slug,
				canvas_assignment_id: null,
				points_possible: ga.points_possible ?? 1,
				deadline: ga.deadline ?? null,
			}),
		);

	const masterAssignments = [...canvasToMaster, ...ghOnlyMaster];

	await batchUpsert(db, "assignments", asRows(masterAssignments), ["slug"]);
	onProgress?.("assignments", `Merged ${masterAssignments.length} master assignments`);
}

/** Pull submissions from Canvas. */
export async function pullSubmissions(
	db: Kysely<Database>,
	canvasClient: KyInstance | null,
	cfg: Config,
	onProgress?: ProgressFn,
): Promise<void> {
	// Canvas submissions (includes grade data)
	if (canvasClient && hasCanvas(cfg)) {
		const assignments = await db.selectFrom("canvas_assignments").select("canvas_id").execute();
		const knownIds = await db.selectFrom("students").select("canvas_id").execute();
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
				posted_grade: s.posted_grade,
				grade_updated_at: s.grade_updated_at,
			}));
			await batchUpsert(db, "canvas_submissions", asRows(rows), [
				"canvas_user_id",
				"canvas_assignment_id",
			]);
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

	// Snapshot synced state (inline columns)
	await snapshotGradesSynced(db);
	await snapshotAssignmentsSynced(db);
	onProgress?.("sync", "Synced baseline columns");
}
