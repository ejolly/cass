/**
 * Change tracking via shadow table diffs.
 * Uses kysely LEFT JOIN to detect pending changes between working and synced tables.
 */
import { type Kysely, sql } from "kysely";
import type { CanvasAssignment, CanvasGrade, Database } from "./schema.ts";

// ─── Snapshot (copy working → synced) ───────────────────────────────

/** Copy all canvas_grades rows into _canvas_grades_synced (replace). */
export async function snapshotCanvasGradesSynced(db: Kysely<Database>): Promise<void> {
	await db.deleteFrom("_canvas_grades_synced").execute();
	await db
		.insertInto("_canvas_grades_synced")
		.columns(["canvas_user_id", "canvas_assignment_id", "posted_grade"])
		.expression(
			db
				.selectFrom("canvas_grades")
				.select(["canvas_user_id", "canvas_assignment_id", "posted_grade"]),
		)
		.execute();
}

/** Copy all canvas_assignments rows into _canvas_assignments_synced (replace). */
export async function snapshotCanvasAssignmentsSynced(db: Kysely<Database>): Promise<void> {
	await db.deleteFrom("_canvas_assignments_synced").execute();
	await db
		.insertInto("_canvas_assignments_synced")
		.columns(["canvas_id", "name", "points_possible", "due_at", "published"])
		.expression(
			db
				.selectFrom("canvas_assignments")
				.select(["canvas_id", "name", "points_possible", "due_at", "published"]),
		)
		.execute();
}

// ─── Pending change detection ───────────────────────────────────────

/** Get grades that differ from synced state (changed or new). */
export async function getPendingGradeChanges(db: Kysely<Database>): Promise<CanvasGrade[]> {
	return db
		.selectFrom("canvas_grades as g")
		.leftJoin("_canvas_grades_synced as s", (join) =>
			join
				.onRef("g.canvas_user_id", "=", "s.canvas_user_id")
				.onRef("g.canvas_assignment_id", "=", "s.canvas_assignment_id"),
		)
		.where((eb) =>
			eb.or([
				eb("g.posted_grade", "!=", eb.ref("s.posted_grade")),
				eb("s.canvas_user_id", "is", null),
			]),
		)
		.selectAll("g")
		.execute();
}

/** Get assignments that differ from synced state (changed or new). */
export async function getPendingAssignmentChanges(
	db: Kysely<Database>,
): Promise<CanvasAssignment[]> {
	return db
		.selectFrom("canvas_assignments as a")
		.leftJoin("_canvas_assignments_synced as s", (join) =>
			join.onRef("a.canvas_id", "=", "s.canvas_id"),
		)
		.where((eb) =>
			eb.or([
				eb("a.name", "!=", eb.ref("s.name")),
				eb("a.points_possible", "!=", eb.ref("s.points_possible")),
				// For nullable columns, use raw comparison
				sql<boolean>`a.due_at IS NOT s.due_at`,
				eb("a.published", "!=", eb.ref("s.published")),
				eb("s.canvas_id", "is", null),
			]),
		)
		.selectAll("a")
		.execute();
}

// ─── Revert to synced state ─────────────────────────────────────────

/** Revert canvas_grades to its synced state by restoring from shadow table. */
export async function revertGrades(db: Kysely<Database>): Promise<number> {
	await db.deleteFrom("canvas_grades").execute();
	await db
		.insertInto("canvas_grades")
		.columns(["canvas_user_id", "canvas_assignment_id", "posted_grade"])
		.expression(
			db
				.selectFrom("_canvas_grades_synced")
				.select(["canvas_user_id", "canvas_assignment_id", "posted_grade"]),
		)
		.execute();
	const count = await db
		.selectFrom("_canvas_grades_synced")
		.select(db.fn.count<number>("canvas_user_id").as("count"))
		.executeTakeFirstOrThrow();
	return count.count;
}

/** Revert canvas_assignments to synced state. */
export async function revertAssignments(db: Kysely<Database>): Promise<number> {
	// Delete working table and restore from synced snapshot
	await db.deleteFrom("canvas_assignments").execute();
	await db
		.insertInto("canvas_assignments")
		.columns(["canvas_id", "name", "points_possible", "due_at", "published"])
		.expression(
			db
				.selectFrom("_canvas_assignments_synced")
				.select(["canvas_id", "name", "points_possible", "due_at", "published"]),
		)
		.execute();

	const pending = await getPendingAssignmentChanges(db);
	return pending.length;
}
