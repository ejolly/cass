import { createCanvasClient, requireConfig, requireDb } from "@/cli/helpers.ts";
import { formatTable } from "@/cli/report.ts";
/**
 * push — push pending changes to Canvas.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("push", "Push pending changes to Canvas")
    .option("--yes, -y", "Skip confirmation")
    .action(async (opts: { yes?: boolean }) => {
      const cfg = await requireConfig();
      const db = await requireDb(cfg);
      const { getPendingGradeChanges, getPendingAssignmentChanges } = await import("@/db/sync.ts");
      const { snapshotGradesSynced, snapshotAssignmentsSynced } = await import("@/db/sync.ts");

      try {
        const pendingGrades = await getPendingGradeChanges(db);
        const pendingAssignments = await getPendingAssignmentChanges(db);

        if (pendingGrades.length === 0 && pendingAssignments.length === 0) {
          consola.info("No pending changes to push");
          return;
        }

        const { buildGradePushData, buildPushPreview, pushGrades } = await import(
          "@/apis/canvas/sync.ts"
        );

        const [gradeData, skipped] = buildGradePushData(pendingGrades);
        const preview = await buildPushPreview(db, gradeData);

        consola.info(
          `${pendingGrades.length} grade change(s), ${pendingAssignments.length} assignment change(s)`,
        );
        if (skipped > 0) consola.warn(`${skipped} grade(s) skipped (invalid)`);

        if (preview.length > 0) {
          const rows = preview.map((p) => ({
            Assignment: p.name,
            Grades: p.count,
            "Manual Post": p.postManually ? "yes" : "",
          }));
          console.log(formatTable(rows, { title: "Grade Push Preview" }));
        }

        if (!opts.yes) {
          const prompts = await import("@clack/prompts");
          const confirm = await prompts.confirm({ message: "Push changes?" });
          if (prompts.isCancel(confirm) || !confirm) {
            consola.info("Cancelled");
            return;
          }
        }

        const client = await createCanvasClient(cfg);
        if (!client) {
          consola.error("Canvas not configured");
          process.exit(1);
        }

        if (Object.keys(gradeData).length > 0) {
          const results = await pushGrades(client, cfg.canvasCourseId, gradeData);
          for (const r of results) {
            if (r.ok) {
              consola.success(`Assignment ${r.canvasAssignmentId}: ${r.count} grade(s) pushed`);
            } else {
              consola.error(`Assignment ${r.canvasAssignmentId}: ${r.error}`);
            }
          }
        }

        await snapshotGradesSynced(db);
        await snapshotAssignmentsSynced(db);
        consola.success("Push complete");
      } finally {
        await db.destroy();
      }
    });
}
