import { createCanvasClient, requireConfig } from "@/cli/helpers.ts";
/**
 * pull — fetch data from APIs into local DB.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("pull", "Fetch data from APIs into local DB")
    .option("--students", "Pull students only")
    .option("--assignments", "Pull assignments only")
    .option("--submissions", "Pull submissions only")
    .action(async (opts: { students?: boolean; assignments?: boolean; submissions?: boolean }) => {
      const cfg = await requireConfig();
      const { join } = await import("node:path");
      const { createDb } = await import("@/db/connection.ts");
      const { up } = await import("@/db/migrations/001_initial.ts");
      const { pullAll, pullStudents, pullAssignments, pullSubmissions } = await import(
        "@/actions/pull.ts"
      );
      const { snapshotGradesSynced, snapshotAssignmentsSynced } = await import("@/db/sync.ts");

      const dbFile = join(cfg.root, "cass.db");
      const db = createDb(dbFile);

      try {
        await up(db as import("kysely").Kysely<unknown>);
      } catch {
        // Migration already applied
      }

      const client = await createCanvasClient(cfg);
      const progress = (step: string, detail: string) => consola.info(`[${step}] ${detail}`);

      try {
        const selective = opts.students || opts.assignments || opts.submissions;
        if (!selective) {
          await pullAll(db, client, cfg, progress);
        } else {
          if (opts.students) await pullStudents(db, client, cfg, progress);
          if (opts.assignments) await pullAssignments(db, client, cfg, progress);
          if (opts.submissions) await pullSubmissions(db, client, cfg, progress);
          await snapshotGradesSynced(db);
          await snapshotAssignmentsSynced(db);
        }
        consola.success("Pull complete");
      } finally {
        await db.destroy();
      }
    });
}
