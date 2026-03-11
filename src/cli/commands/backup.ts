import { requireConfig } from "@/cli/helpers.ts";
/**
 * backup — backup the database.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("backup", "Backup the database")
    .option("-t, --tag <tag>", "Tag appended to filename")
    .option("-l, --list", "List existing backups")
    .action(async (opts: { tag?: string; list?: boolean }) => {
      const cfg = await requireConfig();
      const { join } = await import("node:path");
      const { mkdir, readdir } = await import("node:fs/promises");
      const backupDir = join(cfg.root, "backups");

      if (opts.list) {
        try {
          const files = await readdir(backupDir);
          const dbFiles = files.filter((f) => f.startsWith("cass_") && f.endsWith(".db"));
          if (dbFiles.length === 0) {
            consola.info("No backups found");
            return;
          }
          for (const f of dbFiles.sort().reverse()) {
            console.log(f);
          }
        } catch {
          consola.info("No backups found");
        }
        return;
      }

      const dbFile = join(cfg.root, "cass.db");
      if (!(await Bun.file(dbFile).exists())) {
        consola.error("No database to backup");
        process.exit(1);
      }

      await mkdir(backupDir, { recursive: true });

      const gitignorePath = join(cfg.root, ".gitignore");
      const gitignoreFile = Bun.file(gitignorePath);
      if (await gitignoreFile.exists()) {
        const content = await gitignoreFile.text();
        if (!content.includes("backups/")) {
          await Bun.write(gitignorePath, `${content.trimEnd()}\nbackups/\n`);
        }
      }

      const now = new Date();
      const ts = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const tag = opts.tag ? `_${opts.tag}` : "";
      const backupFile = join(backupDir, `cass_${ts}${tag}.db`);

      await Bun.write(backupFile, Bun.file(dbFile));
      consola.success(`Backup saved: ${backupFile}`);
    });
}
