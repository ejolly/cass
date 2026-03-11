import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { getAllRows, getTableColumns, rawQuery, updateCell } from "@/db/introspection.ts";
import type { Database } from "@/db/schema.ts";
import type { Kysely } from "kysely";
import { createTestDb, seedTestData } from "./helpers.ts";

describe("introspection", () => {
  let db: Kysely<Database>;

  beforeEach(async () => {
    db = await createTestDb();
    await seedTestData(db);
  });

  afterEach(async () => {
    await db.destroy();
  });

  describe("updateCell", () => {
    it("updates a single cell by primary key", async () => {
      await updateCell(db, "students", ["canvas_id"], [100], "name", "Alice Updated");

      const student = await db
        .selectFrom("students")
        .select("name")
        .where("canvas_id", "=", 100)
        .executeTakeFirstOrThrow();
      expect(student.name).toBe("Alice Updated");
    });

    it("updates with composite primary key (canvas_submissions)", async () => {
      await updateCell(
        db,
        "canvas_submissions",
        ["canvas_user_id", "canvas_assignment_id"],
        [100, 9001],
        "posted_grade",
        "10",
      );

      const sub = await db
        .selectFrom("canvas_submissions")
        .select("posted_grade")
        .where("canvas_user_id", "=", 100)
        .where("canvas_assignment_id", "=", 9001)
        .executeTakeFirstOrThrow();
      expect(sub.posted_grade).toBe("10");
    });
  });

  describe("rawQuery", () => {
    it("executes arbitrary SQL", async () => {
      const rows = await rawQuery(db, "SELECT count(*) as n FROM students");
      expect(rows[0]!.n).toBe(3);
    });
  });

  describe("getAllRows", () => {
    it("returns all rows from a table", async () => {
      const rows = await getAllRows(db, "students");
      expect(rows.length).toBe(3);
    });
  });

  describe("getTableColumns", () => {
    it("returns column metadata for students (includes Canvas fields)", async () => {
      const columns = await getTableColumns(db, "students");
      const names = columns.map((c) => c.name);
      expect(names).toContain("canvas_id");
      expect(names).toContain("github_username");
      expect(names).toContain("name");
      expect(names).toContain("sortable_name");
      expect(names).toContain("email");
      expect(names).toContain("login_id");
      expect(names).toContain("sis_user_id");
      expect(names).toContain("sis_section_id");
      expect(names).toContain("excluded");
    });

    it("returns column metadata for canvas_submissions (includes grade + synced)", async () => {
      const columns = await getTableColumns(db, "canvas_submissions");
      const names = columns.map((c) => c.name);
      expect(names).toContain("posted_grade");
      expect(names).toContain("grade_updated_at");
      expect(names).toContain("_synced_posted_grade");
    });
  });
});
