import { requireConfig } from "@/cli/helpers.ts";
/**
 * restore — restore database from backup.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("restore <file>", "Restore database from backup")
    .option("--yes, -y", "Skip confirmation")
    .action(async (file: string, opts: { yes?: boolean }) => {
      const cfg = await requireConfig();
      const { join, resolve } = await import("node:path");

      const backupPath = resolve(file);
      if (!(await Bun.file(backupPath).exists())) {
        consola.error(`Backup file not found: ${backupPath}`);
        process.exit(1);
      }

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Restore from ${backupPath}?` });
        if (prompts.isCancel(confirm) || !confirm) {
          consola.info("Cancelled");
          return;
        }
      }

      const dbFile = join(cfg.root, "cass.db");

      const { unlink } = await import("node:fs/promises");
      for (const suffix of ["-wal", "-shm"]) {
        try {
          await unlink(`${dbFile}${suffix}`);
        } catch {
          // File may not exist
        }
      }

      await Bun.write(dbFile, Bun.file(backupPath));
      consola.success(`Restored from ${backupPath}`);
    });
}
