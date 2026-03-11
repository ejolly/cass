import { describe, expect, it } from "bun:test";
import {
  getPendingAssignmentChanges,
  getPendingGradeChanges,
  revertAssignments,
  revertGrades,
  snapshotAssignmentsSynced,
  snapshotGradesSynced,
} from "@/db/sync.ts";
import { useTestDb } from "./helpers.ts";

describe("sync", () => {
  const getDb = useTestDb();

  describe("snapshotGradesSynced", () => {
    it("copies posted_grade to _synced_posted_grade for all rows", async () => {
      await snapshotGradesSynced(getDb());

      const rows = await getDb()
        .selectFrom("canvas_submissions")
        .select(["posted_grade", "_synced_posted_grade"])
        .execute();

      for (const row of rows) {
        expect(row._synced_posted_grade).toBe(row.posted_grade);
      }
    });
  });

  describe("snapshotAssignmentsSynced", () => {
    it("copies working values to _synced_* columns", async () => {
      await snapshotAssignmentsSynced(getDb());

      const rows = await getDb().selectFrom("canvas_assignments").selectAll().execute();

      for (const row of rows) {
        expect(row._synced_name).toBe(row.name);
        expect(row._synced_points_possible).toBe(row.points_possible);
        expect(row._synced_due_at).toBe(row.due_at);
        expect(row._synced_published).toBe(row.published);
      }
    });
  });

  describe("getPendingGradeChanges", () => {
    it("returns empty when grades match synced", async () => {
      await snapshotGradesSynced(getDb());
      const pending = await getPendingGradeChanges(getDb());
      expect(pending.length).toBe(0);
    });

    it("detects changed posted_grade", async () => {
      await snapshotGradesSynced(getDb());
      await getDb()
        .updateTable("canvas_submissions")
        .set({ posted_grade: "10" })
        .where("canvas_user_id", "=", 100)
        .where("canvas_assignment_id", "=", 9001)
        .execute();

      const pending = await getPendingGradeChanges(getDb());
      expect(pending.length).toBe(1);
      expect(pending[0]!.canvas_user_id).toBe(100);
      expect(pending[0]!.posted_grade).toBe("10");
    });

    it("detects grades not yet synced (synced differs from working)", async () => {
      // Seed data: user 200 has posted_grade='9' but _synced_posted_grade=''
      const pending = await getPendingGradeChanges(getDb());
      expect(pending.length).toBe(1);
      expect(pending[0]!.canvas_user_id).toBe(200);
    });
  });

  describe("getPendingAssignmentChanges", () => {
    it("detects unsynced assignments (synced columns differ)", async () => {
      // hw2 (canvas_id 9002) has _synced_name='' but name='Homework 2'
      const pending = await getPendingAssignmentChanges(getDb());
      expect(pending.length).toBe(1);
      expect(pending[0]!.canvas_id).toBe(9002);
    });

    it("returns empty when all synced", async () => {
      await snapshotAssignmentsSynced(getDb());
      const pending = await getPendingAssignmentChanges(getDb());
      expect(pending.length).toBe(0);
    });

    it("detects changed name", async () => {
      await snapshotAssignmentsSynced(getDb());
      await getDb()
        .updateTable("canvas_assignments")
        .set({ name: "Renamed HW" })
        .where("canvas_id", "=", 9001)
        .execute();

      const pending = await getPendingAssignmentChanges(getDb());
      expect(pending.length).toBe(1);
      expect(pending[0]!.name).toBe("Renamed HW");
    });

    it("detects changed due_at (nullable)", async () => {
      await snapshotAssignmentsSynced(getDb());
      await getDb()
        .updateTable("canvas_assignments")
        .set({ due_at: "2026-03-01T23:59:00Z" })
        .where("canvas_id", "=", 9001)
        .execute();

      const pending = await getPendingAssignmentChanges(getDb());
      expect(pending.length).toBe(1);
    });
  });

  describe("revertGrades", () => {
    it("restores posted_grade from synced baseline", async () => {
      await snapshotGradesSynced(getDb());
      await getDb()
        .updateTable("canvas_submissions")
        .set({ posted_grade: "CHANGED" })
        .where("canvas_user_id", "=", 100)
        .execute();

      const count = await revertGrades(getDb());
      expect(count).toBe(1);

      const row = await getDb()
        .selectFrom("canvas_submissions")
        .select("posted_grade")
        .where("canvas_user_id", "=", 100)
        .where("canvas_assignment_id", "=", 9001)
        .executeTakeFirstOrThrow();
      expect(row.posted_grade).toBe("8");
    });

    it("returns 0 when nothing to revert", async () => {
      await snapshotGradesSynced(getDb());
      const count = await revertGrades(getDb());
      expect(count).toBe(0);
    });
  });

  describe("revertAssignments", () => {
    it("restores assignment fields from synced baseline", async () => {
      await snapshotAssignmentsSynced(getDb());
      await getDb()
        .updateTable("canvas_assignments")
        .set({ name: "CHANGED", published: 0 })
        .where("canvas_id", "=", 9001)
        .execute();

      const count = await revertAssignments(getDb());
      expect(count).toBe(1);

      const row = await getDb()
        .selectFrom("canvas_assignments")
        .select(["name", "published"])
        .where("canvas_id", "=", 9001)
        .executeTakeFirstOrThrow();
      expect(row.name).toBe("Homework 1");
      expect(row.published).toBe(1);
    });

    it("returns 0 when nothing to revert", async () => {
      await snapshotAssignmentsSynced(getDb());
      const count = await revertAssignments(getDb());
      expect(count).toBe(0);
    });
  });
});
