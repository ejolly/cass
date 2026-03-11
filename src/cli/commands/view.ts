import { requireConfig } from "@/cli/helpers.ts";
/**
 * view — open interactive terminal viewer.
 */
import type { CAC } from "cac";

export function register(cli: CAC): void {
  cli.command("view", "Open interactive terminal viewer").action(async () => {
    const consola = (await import("consola")).default;
    const { join } = await import("node:path");

    const cfg = await requireConfig();
    const dbFile = join(cfg.root, "cass.db");

    if (!(await Bun.file(dbFile).exists())) {
      consola.error("No database found. Run 'cassa pull' first.");
      process.exit(1);
    }

    const viewerEntry = join(import.meta.dir, "../../../cassa/src/index.tsx");
    const proc = Bun.spawn(["bun", "--preload", "@opentui/solid/preload", viewerEntry, dbFile], {
      stdin: "inherit",
      stdout: "inherit",
      stderr: "inherit",
      cwd: join(cfg.root, "cassa"),
    });

    await proc.exited;
  });
}
