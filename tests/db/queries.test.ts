import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import type { Kysely } from "kysely";
import {
	queryAssignments,
	queryDataset,
	queryStudents,
	querySubmissions,
} from "../../src/db/queries.ts";
import type { Database } from "../../src/db/schema.ts";
import { createTestDb, seedTestData } from "./helpers.ts";

describe("queries", () => {
	let db: Kysely<Database>;

	beforeEach(async () => {
		db = await createTestDb();
		await seedTestData(db);
	});

	afterEach(async () => {
		await db.destroy();
	});

	describe("queryStudents", () => {
		it("returns enriched student data with github info", async () => {
			const rows = await queryStudents(db);
			expect(rows.length).toBe(3);

			const alice = rows.find((r) => r.name === "Alice Smith");
			expect(alice).toBeDefined();
			expect(alice!.github_username).toBe("alice-gh");
			expect(alice!.canvas_id).toBe(100);
		});

		it("includes students without github accounts", async () => {
			const rows = await queryStudents(db);
			const charlie = rows.find((r) => r.name === "Charlie Brown");
			expect(charlie).toBeDefined();
			expect(charlie!.github_username).toBeNull();
		});
	});

	describe("queryAssignments", () => {
		it("returns enriched assignment data", async () => {
			const rows = await queryAssignments(db);
			expect(rows.length).toBe(2);

			const hw1 = rows.find((r) => r.slug === "hw1");
			expect(hw1).toBeDefined();
			expect(hw1!.title).toBe("Homework 1");
			expect(hw1!.canvas_assignment_id).toBe(9001);
			expect(hw1!.gh_assignment_slug).toBe("hw1");
		});
	});

	describe("querySubmissions", () => {
		it("returns joined submission data", async () => {
			const rows = await querySubmissions(db);
			expect(rows.length).toBeGreaterThan(0);

			// Should have student name and assignment title from JOINs
			const first = rows[0]!;
			expect(first).toHaveProperty("name");
			expect(first).toHaveProperty("title");
			expect(first).toHaveProperty("score");
		});
	});

	describe("queryDataset", () => {
		it("dispatches to students", async () => {
			const rows = await queryDataset(db, "students");
			expect(rows.length).toBe(3);
		});

		it("dispatches to assignments", async () => {
			const rows = await queryDataset(db, "assignments");
			expect(rows.length).toBe(2);
		});

		it("dispatches to submissions", async () => {
			const rows = await queryDataset(db, "submissions");
			expect(rows.length).toBeGreaterThan(0);
		});

		it("supports optional where clause", async () => {
			const rows = await queryDataset(db, "students", { where: "excluded = 0" });
			expect(rows.length).toBe(3);
		});

		it("supports optional limit", async () => {
			const rows = await queryDataset(db, "students", { limit: 1 });
			expect(rows.length).toBe(1);
		});
	});
});
