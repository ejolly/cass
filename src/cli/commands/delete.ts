import { requireConfig } from "@/cli/helpers.ts";
/**
 * delete — delete the local database.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("delete", "Delete the local database")
    .option("--yes, -y", "Skip confirmation")
    .action(async (opts: { yes?: boolean }) => {
      const cfg = await requireConfig();
      const { join } = await import("node:path");
      const { unlink } = await import("node:fs/promises");
      const dbFile = join(cfg.root, "cass.db");

      if (!(await Bun.file(dbFile).exists())) {
        consola.info("No database to delete");
        return;
      }

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Delete ${dbFile}?` });
        if (prompts.isCancel(confirm) || !confirm) {
          consola.info("Cancelled");
          return;
        }
      }

      for (const suffix of ["", "-wal", "-shm"]) {
        try {
          await unlink(`${dbFile}${suffix}`);
        } catch {
          // File may not exist
        }
      }
      consola.success("Database deleted");
    });
}
