import { requireConfig } from "@/cli/helpers.ts";
/**
 * status — show project status.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli.command("status", "Show project status").action(async () => {
    const cfg = await requireConfig();
    const { join } = await import("node:path");

    consola.box(`cassa — ${cfg.canvasBaseUrl || "no Canvas"}`);

    consola.info(`Root: ${cfg.root}`);
    if (cfg.canvasBaseUrl) {
      consola.info(`Canvas: ${cfg.canvasBaseUrl}/courses/${cfg.canvasCourseId}`);
    }
    if (cfg.classroomGhId) {
      consola.info(
        `Classroom: ${cfg.classroomTitle || cfg.classroomSlug} (gh_id=${cfg.classroomGhId})`,
      );
    } else if (cfg.classroomUrl) {
      consola.info(`Classroom: ${cfg.classroomUrl} (pending resolution)`);
    }

    const dbFile = join(cfg.root, "cass.db");
    if (!(await Bun.file(dbFile).exists())) {
      consola.warn("No database found. Run 'cassa pull' to fetch data.");
      return;
    }

    const { createDb } = await import("@/db/connection.ts");
    const db = createDb(dbFile);
    try {
      const students = await db
        .selectFrom("students")
        .select(db.fn.countAll().as("count"))
        .executeTakeFirstOrThrow();
      const assignments = await db
        .selectFrom("assignments")
        .select(db.fn.countAll().as("count"))
        .executeTakeFirstOrThrow();
      const submissions = await db
        .selectFrom("canvas_submissions")
        .select(db.fn.countAll().as("count"))
        .executeTakeFirstOrThrow();

      consola.info(
        `Students: ${students.count}, Assignments: ${assignments.count}, Submissions: ${submissions.count}`,
      );

      const { getPendingGradeChanges, getPendingAssignmentChanges } = await import("@/db/sync.ts");
      const pendingGrades = await getPendingGradeChanges(db);
      const pendingAssignments = await getPendingAssignmentChanges(db);

      if (pendingGrades.length > 0 || pendingAssignments.length > 0) {
        consola.warn(
          `Pending changes: ${pendingGrades.length} grade(s), ${pendingAssignments.length} assignment(s)`,
        );
      } else {
        consola.success("No pending changes");
      }
    } finally {
      await db.destroy();
    }
  });
}
