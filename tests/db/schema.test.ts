import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { type Kysely, sql } from "kysely";
import type { Database } from "../../src/db/schema.ts";
import { createTestDb, seedTestData } from "./helpers.ts";

describe("schema & migration", () => {
	let db: Kysely<Database>;

	beforeEach(async () => {
		db = await createTestDb();
	});

	afterEach(async () => {
		await db.destroy();
	});

	it("creates all 12 tables", async () => {
		const tables = await db.introspection.getTables();
		const tableNames = tables.map((t) => t.name).sort();
		expect(tableNames).toEqual([
			"_canvas_assignments_synced",
			"_canvas_grades_synced",
			"assignments",
			"canvas_assignments",
			"canvas_grades",
			"canvas_students",
			"canvas_submissions",
			"gh_assignments",
			"gh_students",
			"gh_submissions",
			"meta",
			"students",
		]);
	});

	it("sets schema_version to 15", async () => {
		const row = await db
			.selectFrom("meta")
			.select("value")
			.where("key", "=", "schema_version")
			.executeTakeFirstOrThrow();
		expect(row.value).toBe("15");
	});

	it("inserts and queries students", async () => {
		await sql`INSERT INTO students (canvas_id, name) VALUES (1, 'Test User')`.execute(db);

		const student = await db
			.selectFrom("students")
			.selectAll()
			.where("canvas_id", "=", 1)
			.executeTakeFirstOrThrow();

		expect(student.name).toBe("Test User");
		expect(student.excluded).toBe(0);
		expect(student.email).toBe("");
		expect(student.github_username).toBeNull();
	});

	it("enforces unique github_username on students", async () => {
		await sql`INSERT INTO students (canvas_id, github_username, name) VALUES (1, 'alice', 'Alice')`.execute(
			db,
		);

		expect(
			sql`INSERT INTO students (canvas_id, github_username, name) VALUES (2, 'alice', 'Alice2')`.execute(
				db,
			),
		).rejects.toThrow();
	});

	it("supports composite primary key on canvas_submissions", async () => {
		const now = Date.now() / 1000;
		await sql`INSERT INTO canvas_submissions (canvas_user_id, canvas_assignment_id, fetched_at) VALUES (1, 1, ${now})`.execute(
			db,
		);

		// Same composite key should fail
		expect(
			sql`INSERT INTO canvas_submissions (canvas_user_id, canvas_assignment_id, fetched_at) VALUES (1, 1, ${now})`.execute(
				db,
			),
		).rejects.toThrow();

		// Different combo should succeed
		await sql`INSERT INTO canvas_submissions (canvas_user_id, canvas_assignment_id, fetched_at) VALUES (1, 2, ${now})`.execute(
			db,
		);
	});

	it("seeds test data without errors", async () => {
		await seedTestData(db);

		const studentCount = await db
			.selectFrom("students")
			.select(db.fn.count<number>("canvas_id").as("count"))
			.executeTakeFirstOrThrow();
		expect(studentCount.count).toBe(3);

		const ghSubCount = await db
			.selectFrom("gh_submissions")
			.select(db.fn.count<number>("github_username").as("count"))
			.executeTakeFirstOrThrow();
		expect(ghSubCount.count).toBe(2);
	});
});
