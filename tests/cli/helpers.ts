import { afterEach, beforeEach } from "bun:test";
/**
 * CLI test helpers — subprocess runner and project scaffolding.
 */
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BIN = join(import.meta.dir, "../../src/index.ts");

/** Run cassa CLI as a subprocess and return stdout/stderr/exitCode. */
export async function run(args: string[], opts?: { cwd?: string }) {
  const proc = Bun.spawn(["bun", BIN, ...args], {
    cwd: opts?.cwd ?? process.cwd(),
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  const exitCode = await proc.exited;
  return { stdout, stderr, output: stdout + stderr, exitCode };
}

/**
 * Sets up beforeEach/afterEach hooks that create a temp directory
 * with a cass.toml. Returns a getter for the current tmpDir path.
 */
export function useProjectDir(opts?: { withDb?: boolean }): () => string {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "cassa-test-"));
    await writeFile(
      join(tmpDir, "cass.toml"),
      `[canvas]\nbase_url = "https://canvas.test.edu"\ncourse_id = 123\n`,
    );
    if (opts?.withDb) {
      const { createDb } = await import("@/db/connection.ts");
      const { up } = await import("@/db/migrations/001_initial.ts");
      const db = createDb(join(tmpDir, "cass.db"));
      await up(db as Parameters<typeof up>[0]);
      await db.destroy();
    }
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  return () => tmpDir;
}
