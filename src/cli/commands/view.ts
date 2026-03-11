import { requireConfig } from "@/cli/helpers.ts";
/**
 * view — open interactive terminal viewer.
 */
import type { CAC } from "cac";

export function register(cli: CAC): void {
  cli.command("view", "Open interactive terminal viewer").action(async () => {
    const consola = (await import("consola")).default;
    const { join, dirname } = await import("node:path");
    const { realpath } = await import("node:fs/promises");

    const cfg = await requireConfig();
    const dbFile = join(cfg.root, "cass.db");

    if (!(await Bun.file(dbFile).exists())) {
      consola.error("No database found. Run 'cassa pull' first.");
      process.exit(1);
    }

    // Resolve project root from the real path of the running binary.
    // Works for both: compiled binary at dist/cassa (go up 1) and
    // dev mode running src/cli/commands/view.ts (go up 3).
    const execPath = await realpath(process.execPath);
    const isCompiled = !execPath.endsWith("bun");
    const projectRoot = isCompiled ? dirname(dirname(execPath)) : join(import.meta.dir, "../../..");

    const viewerEntry = join(projectRoot, "cassa/src/index.tsx");
    if (!(await Bun.file(viewerEntry).exists())) {
      consola.error(`Viewer not found at ${viewerEntry}. Is the cass source tree intact?`);
      process.exit(1);
    }

    const proc = Bun.spawn(["bun", "--preload", "@opentui/solid/preload", viewerEntry, dbFile], {
      stdin: "inherit",
      stdout: "inherit",
      stderr: "inherit",
      cwd: join(projectRoot, "cassa"),
    });

    await proc.exited;
  });
}
