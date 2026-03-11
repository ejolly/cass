/**
 * Test helpers — in-memory DB with schema applied.
 */
import { type Kysely, sql } from "kysely";
import { up } from "../../migrations/001_initial.ts";
import { createDb } from "../../src/db/connection.ts";
import type { Database } from "../../src/db/schema.ts";

/** Create a fresh in-memory DB with the full schema applied. */
export async function createTestDb(): Promise<Kysely<Database>> {
	const db = createDb(":memory:");
	await up(db as Kysely<unknown>);
	return db;
}

/** Seed minimal test data for common test scenarios. */
export async function seedTestData(db: Kysely<Database>) {
	const now = Date.now() / 1000;

	// Use raw SQL for seed data to avoid kysely's DEFAULT keyword issue with SQLite
	await sql`INSERT INTO canvas_students (canvas_id, name) VALUES (100, 'Alice Smith'), (200, 'Bob Jones'), (300, 'Charlie Brown')`.execute(
		db,
	);

	await sql`INSERT INTO gh_students (github_username, github_id, name) VALUES ('alice-gh', 1001, 'Alice Smith'), ('bob-gh', 1002, 'Bob Jones')`.execute(
		db,
	);

	await sql`INSERT INTO students (canvas_id, github_username, name) VALUES (100, 'alice-gh', 'Alice Smith'), (200, 'bob-gh', 'Bob Jones'), (300, NULL, 'Charlie Brown')`.execute(
		db,
	);

	await sql`INSERT INTO gh_assignments (slug, gh_id, title, points_possible, deadline) VALUES ('hw1', 5001, 'Homework 1', 10, '2026-02-01T23:59:00Z'), ('hw2', 5002, 'Homework 2', 20, NULL)`.execute(
		db,
	);

	await sql`INSERT INTO canvas_assignments (canvas_id, name, points_possible, published) VALUES (9001, 'Homework 1', 10, 1), (9002, 'Homework 2', 20, 0)`.execute(
		db,
	);

	await sql`INSERT INTO assignments (slug, title, gh_assignment_slug, canvas_assignment_id, points_possible) VALUES ('hw1', 'Homework 1', 'hw1', 9001, 10), ('hw2', 'Homework 2', 'hw2', 9002, 20)`.execute(
		db,
	);

	await sql`INSERT INTO canvas_submissions (canvas_user_id, canvas_assignment_id, submitted, score, fetched_at) VALUES (100, 9001, 1, 8, ${now}), (200, 9001, 1, 9, ${now})`.execute(
		db,
	);

	await sql`INSERT INTO canvas_grades (canvas_user_id, canvas_assignment_id, score, posted_grade, updated_at) VALUES (100, 9001, 8, '8', ${now}), (200, 9001, 9, '9', ${now})`.execute(
		db,
	);

	await sql`INSERT INTO gh_submissions (github_username, assignment_slug, submitted, commit_count, passing, fetched_at) VALUES ('alice-gh', 'hw1', 1, 5, 1, ${now}), ('bob-gh', 'hw1', 1, 3, 0, ${now})`.execute(
		db,
	);

	// Shadow tables (synced state) — only partially synced for testing diffs
	await sql`INSERT INTO _canvas_assignments_synced (canvas_id, name, points_possible, published) VALUES (9001, 'Homework 1', 10, 1)`.execute(
		db,
	);

	await sql`INSERT INTO _canvas_grades_synced (canvas_user_id, canvas_assignment_id, posted_grade) VALUES (100, 9001, '8')`.execute(
		db,
	);
}
