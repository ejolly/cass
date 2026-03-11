import { requireConfig, requireDb } from "@/cli/helpers.ts";
/**
 * revert — revert pending changes to last synced state.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("revert", "Revert pending changes to last synced state")
    .option("--yes, -y", "Skip confirmation")
    .action(async (opts: { yes?: boolean }) => {
      const cfg = await requireConfig();
      const db = await requireDb(cfg);
      const {
        getPendingGradeChanges,
        getPendingAssignmentChanges,
        revertGrades,
        revertAssignments,
      } = await import("@/db/sync.ts");

      try {
        const pendingGrades = await getPendingGradeChanges(db);
        const pendingAssignments = await getPendingAssignmentChanges(db);

        if (pendingGrades.length === 0 && pendingAssignments.length === 0) {
          consola.info("No pending changes to revert");
          return;
        }

        consola.info(
          `${pendingGrades.length} grade change(s), ${pendingAssignments.length} assignment change(s)`,
        );

        if (!opts.yes) {
          const prompts = await import("@clack/prompts");
          const confirm = await prompts.confirm({ message: "Revert all pending changes?" });
          if (prompts.isCancel(confirm) || !confirm) {
            consola.info("Cancelled");
            return;
          }
        }

        const revertedG = await revertGrades(db);
        const revertedA = await revertAssignments(db);
        consola.success(`Reverted ${revertedG} grade(s), ${revertedA} assignment(s)`);
      } finally {
        await db.destroy();
      }
    });
}
