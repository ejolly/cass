import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import type { Kysely } from "kysely";
import type { Database } from "../../src/db/schema.ts";
import {
	getPendingAssignmentChanges,
	getPendingGradeChanges,
	snapshotCanvasAssignmentsSynced,
	snapshotCanvasGradesSynced,
} from "../../src/db/sync.ts";
import { createTestDb, seedTestData } from "./helpers.ts";

describe("sync", () => {
	let db: Kysely<Database>;

	beforeEach(async () => {
		db = await createTestDb();
		await seedTestData(db);
	});

	afterEach(async () => {
		await db.destroy();
	});

	describe("snapshotCanvasGradesSynced", () => {
		it("copies current grades to synced table", async () => {
			await snapshotCanvasGradesSynced(db);

			const synced = await db.selectFrom("_canvas_grades_synced").selectAll().execute();

			// Should have all grades from canvas_grades
			expect(synced.length).toBe(2);
		});
	});

	describe("snapshotCanvasAssignmentsSynced", () => {
		it("copies current assignments to synced table", async () => {
			await snapshotCanvasAssignmentsSynced(db);

			const synced = await db.selectFrom("_canvas_assignments_synced").selectAll().execute();

			expect(synced.length).toBe(2);
		});
	});

	describe("getPendingGradeChanges", () => {
		it("returns empty when grades match synced", async () => {
			// Snapshot so everything is synced
			await snapshotCanvasGradesSynced(db);
			const pending = await getPendingGradeChanges(db);
			expect(pending.length).toBe(0);
		});

		it("detects changed posted_grade", async () => {
			// Change a grade after syncing
			await snapshotCanvasGradesSynced(db);
			await db
				.updateTable("canvas_grades")
				.set({ posted_grade: "10" })
				.where("canvas_user_id", "=", 100)
				.where("canvas_assignment_id", "=", 9001)
				.execute();

			const pending = await getPendingGradeChanges(db);
			expect(pending.length).toBe(1);
			expect(pending[0]!.canvas_user_id).toBe(100);
			expect(pending[0]!.posted_grade).toBe("10");
		});

		it("detects new grades not yet synced", async () => {
			// Bob's grade for hw1 is in canvas_grades but user_id 200 grade for 9001
			// was already seeded. Snapshot only has user 100.
			// So user 200 should show as pending.
			const pending = await getPendingGradeChanges(db);
			expect(pending.length).toBe(1);
			expect(pending[0]!.canvas_user_id).toBe(200);
		});
	});

	describe("getPendingAssignmentChanges", () => {
		it("detects new assignments not yet synced", async () => {
			// hw2 (canvas_id 9002) was not seeded into synced table
			const pending = await getPendingAssignmentChanges(db);
			expect(pending.length).toBe(1);
			expect(pending[0]!.canvas_id).toBe(9002);
		});

		it("returns empty when all synced", async () => {
			await snapshotCanvasAssignmentsSynced(db);
			const pending = await getPendingAssignmentChanges(db);
			expect(pending.length).toBe(0);
		});
	});
});
