/**
 * Typed queries — replaces manual SQL builders from Python queries.py.
 * Uses kysely JOINs for enriched datasets.
 */
import { type Kysely, type SqlBool, sql } from "kysely";
import { match } from "ts-pattern";
import type { Database } from "./schema.ts";

export type Dataset = "students" | "assignments" | "submissions" | "gradebook";

export interface QueryOptions {
	where?: string;
	order?: string;
	limit?: number;
}

/** Enriched students: master students with all available fields. */
export async function queryStudents(db: Kysely<Database>, opts: QueryOptions = {}) {
	let query = db.selectFrom("students").selectAll("students");

	if (opts.where) query = query.where(sql.raw<SqlBool>(opts.where));
	if (opts.order) query = query.orderBy(sql.raw(opts.order));
	if (opts.limit) query = query.limit(opts.limit);

	return query.execute();
}

/** Enriched assignments: master assignments with all available fields. */
export async function queryAssignments(db: Kysely<Database>, opts: QueryOptions = {}) {
	let query = db.selectFrom("assignments").selectAll("assignments");

	if (opts.where) query = query.where(sql.raw<SqlBool>(opts.where));
	if (opts.order) query = query.orderBy(sql.raw(opts.order));
	if (opts.limit) query = query.limit(opts.limit);

	return query.execute();
}

/** Submissions joined with student names and assignment titles. */
export async function querySubmissions(db: Kysely<Database>, opts: QueryOptions = {}) {
	let query = db
		.selectFrom("canvas_submissions as cs")
		.innerJoin("students as s", "s.canvas_id", "cs.canvas_user_id")
		.innerJoin("assignments as a", "a.canvas_assignment_id", "cs.canvas_assignment_id")
		.select([
			"s.name",
			"a.title",
			"a.slug",
			"cs.canvas_user_id",
			"cs.canvas_assignment_id",
			"cs.submitted",
			"cs.score",
			"cs.late",
			"cs.workflow_state",
			"cs.submitted_at",
		]);

	if (opts.where) query = query.where(sql.raw<SqlBool>(opts.where));
	if (opts.order) query = query.orderBy(sql.raw(opts.order));
	if (opts.limit) query = query.limit(opts.limit);

	return query.execute();
}

/** Dispatch to the appropriate dataset query using ts-pattern. */
export function queryDataset(
	db: Kysely<Database>,
	dataset: Dataset,
	opts: QueryOptions = {},
): Promise<Record<string, unknown>[]> {
	return match(dataset)
		.with("students", () => queryStudents(db, opts))
		.with("assignments", () => queryAssignments(db, opts))
		.with("submissions", () => querySubmissions(db, opts))
		.with("gradebook", () => queryGradebook(db, opts))
		.exhaustive() as Promise<Record<string, unknown>[]>;
}

/** Gradebook — placeholder for the matrix pivot view. */
export async function queryGradebook(db: Kysely<Database>, opts: QueryOptions = {}) {
	let query = db
		.selectFrom("canvas_submissions as cs")
		.innerJoin("students as s", "s.canvas_id", "cs.canvas_user_id")
		.innerJoin("assignments as a", "a.canvas_assignment_id", "cs.canvas_assignment_id")
		.select(["s.name", "a.title", "cs.score"]);

	if (opts.where) query = query.where(sql.raw<SqlBool>(opts.where));
	if (opts.order) query = query.orderBy(sql.raw(opts.order));
	if (opts.limit) query = query.limit(opts.limit);

	return query.execute();
}
