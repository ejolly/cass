import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import type { Database } from "@/db/schema.ts";
import { type Kysely, sql } from "kysely";
import { createTestDb, seedTestData } from "./helpers.ts";

describe("schema & migration", () => {
  let db: Kysely<Database>;

  beforeEach(async () => {
    db = await createTestDb();
  });

  afterEach(async () => {
    await db.destroy();
  });

  it("creates all 8 tables", async () => {
    const tables = await db.introspection.getTables();
    const tableNames = tables.map((t) => t.name).sort();
    expect(tableNames).toEqual([
      "assignments",
      "canvas_assignments",
      "canvas_submissions",
      "gh_assignments",
      "gh_students",
      "gh_submissions",
      "meta",
      "students",
    ]);
  });

  it("sets schema_version to 16", async () => {
    const row = await db
      .selectFrom("meta")
      .select("value")
      .where("key", "=", "schema_version")
      .executeTakeFirstOrThrow();
    expect(row.value).toBe("16");
  });

  it("inserts and queries students with Canvas-specific fields", async () => {
    await sql`INSERT INTO students (canvas_id, name, sortable_name, login_id) VALUES (1, 'Test User', 'User, Test', 'tuser')`.execute(
      db,
    );

    const student = await db
      .selectFrom("students")
      .selectAll()
      .where("canvas_id", "=", 1)
      .executeTakeFirstOrThrow();

    expect(student.name).toBe("Test User");
    expect(student.sortable_name).toBe("User, Test");
    expect(student.login_id).toBe("tuser");
    expect(student.excluded).toBe(0);
    expect(student.email).toBe("");
    expect(student.sis_user_id).toBe("");
    expect(student.sis_section_id).toBe("");
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

  it("canvas_submissions has inline grade and synced columns", async () => {
    const now = Date.now() / 1000;
    await sql`INSERT INTO canvas_submissions (canvas_user_id, canvas_assignment_id, fetched_at, posted_grade, grade_updated_at, _synced_posted_grade)
			VALUES (1, 1, ${now}, 'A', ${now}, '')`.execute(db);

    const sub = await db
      .selectFrom("canvas_submissions")
      .selectAll()
      .where("canvas_user_id", "=", 1)
      .executeTakeFirstOrThrow();

    expect(sub.posted_grade).toBe("A");
    expect(sub.grade_updated_at).toBeCloseTo(now, 0);
    expect(sub._synced_posted_grade).toBe("");
  });

  it("canvas_assignments has inline synced columns", async () => {
    await sql`INSERT INTO canvas_assignments (canvas_id, name, _synced_name) VALUES (1, 'HW 1', 'HW 1')`.execute(
      db,
    );

    const assignment = await db
      .selectFrom("canvas_assignments")
      .selectAll()
      .where("canvas_id", "=", 1)
      .executeTakeFirstOrThrow();

    expect(assignment._synced_name).toBe("HW 1");
    expect(assignment._synced_points_possible).toBe(0);
    expect(assignment._synced_published).toBe(0);
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
