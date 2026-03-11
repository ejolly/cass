/**
 * Change tracking via inline _synced_* columns.
 * Compares working values against synced baselines to detect pending changes.
 */
import { type Kysely, sql } from "kysely";
import type { CanvasAssignment, CanvasSubmission, Database } from "./schema.ts";

// ─── Snapshot (copy working → synced columns) ───────────────────────

/** Snapshot current grades: set _synced_posted_grade = posted_grade for all rows. */
export async function snapshotGradesSynced(db: Kysely<Database>): Promise<void> {
	await db
		.updateTable("canvas_submissions")
		.set({ _synced_posted_grade: sql`posted_grade` })
		.execute();
}

/** Snapshot current assignments: set _synced_* = working values for all rows. */
export async function snapshotAssignmentsSynced(db: Kysely<Database>): Promise<void> {
	await db
		.updateTable("canvas_assignments")
		.set({
			_synced_name: sql`name`,
			_synced_points_possible: sql`points_possible`,
			_synced_due_at: sql`due_at`,
			_synced_published: sql`published`,
		})
		.execute();
}

// ─── Pending change detection ───────────────────────────────────────

/** Get submissions with grades that differ from synced state. */
export async function getPendingGradeChanges(db: Kysely<Database>): Promise<CanvasSubmission[]> {
	return db
		.selectFrom("canvas_submissions")
		.where((eb) => eb("posted_grade", "!=", eb.ref("_synced_posted_grade")))
		.selectAll()
		.execute();
}

/** Get assignments that differ from synced state. */
export async function getPendingAssignmentChanges(
	db: Kysely<Database>,
): Promise<CanvasAssignment[]> {
	return db
		.selectFrom("canvas_assignments")
		.where((eb) =>
			eb.or([
				eb("name", "!=", eb.ref("_synced_name")),
				eb("points_possible", "!=", eb.ref("_synced_points_possible")),
				sql<boolean>`due_at IS NOT _synced_due_at`,
				eb("published", "!=", eb.ref("_synced_published")),
			]),
		)
		.selectAll()
		.execute();
}

// ─── Revert to synced state ─────────────────────────────────────────

/** Revert grades to synced baseline. Returns count of reverted rows. */
export async function revertGrades(db: Kysely<Database>): Promise<number> {
	const pending = await getPendingGradeChanges(db);
	if (pending.length === 0) return 0;

	await db
		.updateTable("canvas_submissions")
		.set({ posted_grade: sql`_synced_posted_grade` })
		.where((eb) => eb("posted_grade", "!=", eb.ref("_synced_posted_grade")))
		.execute();
	return pending.length;
}

/** Revert assignments to synced baseline. Returns count of reverted rows. */
export async function revertAssignments(db: Kysely<Database>): Promise<number> {
	const pending = await getPendingAssignmentChanges(db);
	if (pending.length === 0) return 0;

	await db
		.updateTable("canvas_assignments")
		.set({
			name: sql`_synced_name`,
			points_possible: sql`_synced_points_possible`,
			due_at: sql`_synced_due_at`,
			published: sql`_synced_published`,
		})
		.where((eb) =>
			eb.or([
				eb("name", "!=", eb.ref("_synced_name")),
				eb("points_possible", "!=", eb.ref("_synced_points_possible")),
				sql<boolean>`due_at IS NOT _synced_due_at`,
				eb("published", "!=", eb.ref("_synced_published")),
			]),
		)
		.execute();
	return pending.length;
}
