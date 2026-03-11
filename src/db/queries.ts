/**
 * Typed queries — replaces manual SQL builders from Python queries.py.
 * Uses kysely JOINs for enriched datasets.
 */
import { type Kysely, type SelectQueryBuilder, type SqlBool, sql } from "kysely";
import { match } from "ts-pattern";
import type { Database } from "./schema.ts";

export type Dataset = "students" | "assignments" | "submissions" | "gradebook";

export interface QueryOptions {
  where?: string;
  order?: string;
  limit?: number;
}

/** Apply optional where/order/limit clauses to any select query. */
// biome-ignore lint/suspicious/noExplicitAny: Kysely JOIN queries produce extended DB types that can't be captured with keyof Database
function applyOpts<DB extends Record<string, any>, TB extends keyof DB & string, O>(
  query: SelectQueryBuilder<DB, TB, O>,
  opts: QueryOptions,
): SelectQueryBuilder<DB, TB, O> {
  let q = query;
  if (opts.where) q = q.where(sql.raw<SqlBool>(opts.where));
  if (opts.order) q = q.orderBy(sql.raw(opts.order));
  if (opts.limit) q = q.limit(opts.limit);
  return q;
}

/** Enriched students: master students with all available fields. */
export function queryStudents(db: Kysely<Database>, opts: QueryOptions = {}) {
  return applyOpts(db.selectFrom("students").selectAll("students"), opts).execute();
}

/** Enriched assignments: master assignments with all available fields. */
export function queryAssignments(db: Kysely<Database>, opts: QueryOptions = {}) {
  return applyOpts(db.selectFrom("assignments").selectAll("assignments"), opts).execute();
}

/** Submissions joined with student names and assignment titles. */
export function querySubmissions(db: Kysely<Database>, opts: QueryOptions = {}) {
  return applyOpts(
    db
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
        "cs.posted_grade",
        "cs.late",
        "cs.workflow_state",
        "cs.submitted_at",
      ]),
    opts,
  ).execute();
}

/** Gradebook — score + posted_grade from canvas_submissions (no join to grades needed). */
export function queryGradebook(db: Kysely<Database>, opts: QueryOptions = {}) {
  return applyOpts(
    db
      .selectFrom("canvas_submissions as cs")
      .innerJoin("students as s", "s.canvas_id", "cs.canvas_user_id")
      .innerJoin("assignments as a", "a.canvas_assignment_id", "cs.canvas_assignment_id")
      .select(["s.name", "a.title", "cs.score", "cs.posted_grade"]),
    opts,
  ).execute();
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
