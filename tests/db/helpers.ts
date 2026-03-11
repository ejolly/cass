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

  // Students (master — includes Canvas-specific fields, merged from canvas_students)
  await sql`INSERT INTO students (canvas_id, github_username, name, sortable_name, email, login_id, sis_user_id, sis_section_id)
		VALUES
			(100, 'alice-gh', 'Alice Smith', 'Smith, Alice', 'alice@test.com', 'asmith', 'A12345', 'SEC01'),
			(200, 'bob-gh', 'Bob Jones', 'Jones, Bob', 'bob@test.com', 'bjones', 'B67890', 'SEC01'),
			(300, NULL, 'Charlie Brown', 'Brown, Charlie', 'charlie@test.com', 'cbrown', 'C11111', 'SEC02')`.execute(
    db,
  );

  await sql`INSERT INTO gh_students (github_username, github_id, name) VALUES ('alice-gh', 1001, 'Alice Smith'), ('bob-gh', 1002, 'Bob Jones')`.execute(
    db,
  );

  await sql`INSERT INTO gh_assignments (slug, gh_id, title, points_possible, deadline) VALUES ('hw1', 5001, 'Homework 1', 10, '2026-02-01T23:59:00Z'), ('hw2', 5002, 'Homework 2', 20, NULL)`.execute(
    db,
  );

  await sql`INSERT INTO canvas_assignments (canvas_id, name, points_possible, published, _synced_name, _synced_points_possible, _synced_published)
		VALUES
			(9001, 'Homework 1', 10, 1, 'Homework 1', 10, 1),
			(9002, 'Homework 2', 20, 0, '', 0, 0)`.execute(db);

  await sql`INSERT INTO assignments (slug, title, gh_assignment_slug, canvas_assignment_id, points_possible) VALUES ('hw1', 'Homework 1', 'hw1', 9001, 10), ('hw2', 'Homework 2', 'hw2', 9002, 20)`.execute(
    db,
  );

  // Canvas submissions (merged with grades — includes posted_grade + synced baseline)
  await sql`INSERT INTO canvas_submissions (canvas_user_id, canvas_assignment_id, submitted, score, fetched_at, posted_grade, grade_updated_at, _synced_posted_grade)
		VALUES
			(100, 9001, 1, 8, ${now}, '8', ${now}, '8'),
			(200, 9001, 1, 9, ${now}, '9', ${now}, '')`.execute(db);

  await sql`INSERT INTO gh_submissions (github_username, assignment_slug, submitted, commit_count, passing, fetched_at) VALUES ('alice-gh', 'hw1', 1, 5, 1, ${now}), ('bob-gh', 'hw1', 1, 3, 0, ${now})`.execute(
    db,
  );
}
