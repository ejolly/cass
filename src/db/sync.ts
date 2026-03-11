/**
 * Change tracking via shadow table diffs.
 * Uses kysely LEFT JOIN to detect pending changes between working and synced tables.
 */
import { type Kysely, sql } from "kysely";
import type { CanvasAssignment, CanvasGrade, Database } from "./schema.ts";

// ─── Snapshot (copy working → synced) ───────────────────────────────

/** Copy all canvas_grades rows into _canvas_grades_synced (replace). */
export async function snapshotCanvasGradesSynced(db: Kysely<Database>): Promise<void> {
	await sql`DELETE FROM _canvas_grades_synced`.execute(db);
	await sql`
		INSERT INTO _canvas_grades_synced (canvas_user_id, canvas_assignment_id, posted_grade)
		SELECT canvas_user_id, canvas_assignment_id, posted_grade
		FROM canvas_grades
	`.execute(db);
}

/** Copy all canvas_assignments rows into _canvas_assignments_synced (replace). */
export async function snapshotCanvasAssignmentsSynced(db: Kysely<Database>): Promise<void> {
	await sql`DELETE FROM _canvas_assignments_synced`.execute(db);
	await sql`
		INSERT INTO _canvas_assignments_synced (canvas_id, name, points_possible, due_at, published)
		SELECT canvas_id, name, points_possible, due_at, published
		FROM canvas_assignments
	`.execute(db);
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

/** Revert a working table to its synced state. */
export async function revertGrades(db: Kysely<Database>): Promise<number> {
	await sql`DELETE FROM canvas_grades`.execute(db);
	await sql`
		INSERT INTO canvas_grades (canvas_user_id, canvas_assignment_id, score, posted_grade, updated_at)
		SELECT g.canvas_user_id, g.canvas_assignment_id, g.score, s.posted_grade, g.updated_at
		FROM canvas_grades AS g
		INNER JOIN _canvas_grades_synced AS s
			ON g.canvas_user_id = s.canvas_user_id
			AND g.canvas_assignment_id = s.canvas_assignment_id
	`.execute(db);
	const count = await db
		.selectFrom("_canvas_grades_synced")
		.select(db.fn.count<number>("canvas_user_id").as("count"))
		.executeTakeFirstOrThrow();
	return count.count;
}

/** Revert canvas_assignments to synced state. */
export async function revertAssignments(db: Kysely<Database>): Promise<number> {
	// Restore synced values for existing rows, delete rows not in synced
	await sql`
		UPDATE canvas_assignments SET
			name = (SELECT s.name FROM _canvas_assignments_synced s WHERE s.canvas_id = canvas_assignments.canvas_id),
			points_possible = (SELECT s.points_possible FROM _canvas_assignments_synced s WHERE s.canvas_id = canvas_assignments.canvas_id),
			due_at = (SELECT s.due_at FROM _canvas_assignments_synced s WHERE s.canvas_id = canvas_assignments.canvas_id),
			published = (SELECT s.published FROM _canvas_assignments_synced s WHERE s.canvas_id = canvas_assignments.canvas_id)
		WHERE canvas_id IN (SELECT canvas_id FROM _canvas_assignments_synced)
	`.execute(db);

	const pending = await getPendingAssignmentChanges(db);
	return pending.length;
}
