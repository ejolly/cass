import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BIN = join(import.meta.dir, "../../src/index.ts");

/** Run cassa CLI and return stdout + stderr + exit code + combined output. */
async function run(args: string[], opts?: { cwd?: string }) {
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
  return {
    stdout,
    stderr,
    output: stdout + stderr,
    exitCode,
  };
}

describe("CLI basics", () => {
  it("shows help with --help", async () => {
    const { stdout, exitCode } = await run(["--help"]);
    expect(exitCode).toBe(0);
    expect(stdout).toContain("cassa");
    expect(stdout).toContain("pull");
    expect(stdout).toContain("push");
    expect(stdout).toContain("status");
  });

  it("shows version with --version", async () => {
    const { stdout, exitCode } = await run(["--version"]);
    expect(exitCode).toBe(0);
    expect(stdout).toContain("0.1.0");
  });

  it("shows help when invoked with no args", async () => {
    const { stdout } = await run([]);
    expect(stdout).toContain("cassa");
  });
});

describe("commands requiring project root", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "cassa-test-"));
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  it("status fails without cass.toml", async () => {
    const result = await run(["status"], { cwd: tmpDir });
    expect(result.exitCode).not.toBe(0);
    expect(result.output).toContain("cass.toml");
  });

  it("delete fails without cass.toml", async () => {
    const result = await run(["delete", "--yes"], { cwd: tmpDir });
    expect(result.exitCode).not.toBe(0);
  });

  describe("with a cass.toml project", () => {
    beforeEach(async () => {
      await writeFile(
        join(tmpDir, "cass.toml"),
        `[canvas]\nbase_url = "https://canvas.test.edu"\ncourse_id = 123\n`,
      );
    });

    it("status shows config info", async () => {
      const { output, exitCode } = await run(["status"], { cwd: tmpDir });
      expect(exitCode).toBe(0);
      expect(output).toContain("canvas.test.edu");
    });

    it("query fails without DB", async () => {
      const result = await run(["query", "students"], { cwd: tmpDir });
      expect(result.exitCode).not.toBe(0);
    });

    it("delete --yes succeeds even without DB", async () => {
      const { exitCode } = await run(["delete", "--yes"], { cwd: tmpDir });
      expect(exitCode).toBe(0);
    });

    it("backup --list works with no backups", async () => {
      const { output, exitCode } = await run(["backup", "--list"], { cwd: tmpDir });
      expect(exitCode).toBe(0);
      expect(output).toContain("No backups");
    });
  });
});

describe("query with in-memory-like DB", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "cassa-test-"));
    await writeFile(
      join(tmpDir, "cass.toml"),
      `[canvas]\nbase_url = "https://canvas.test.edu"\ncourse_id = 123\n`,
    );
    // Create DB with schema via a small setup script
    const setupScript = `
			import { createDb } from "${BIN.replace("index.ts", "db/connection.ts")}";
			import { up } from "${join(import.meta.dir, "../../migrations/001_initial.ts")}";
			const db = createDb("${join(tmpDir, "cass.db")}");
			await up(db);
			await db.destroy();
		`;
    const setupProc = Bun.spawn(["bun", "-e", setupScript], { stdout: "ignore", stderr: "ignore" });
    await setupProc.exited;
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true });
  });

  it("query students returns empty table", async () => {
    const { stdout, exitCode } = await run(["query", "students"], { cwd: tmpDir });
    expect(exitCode).toBe(0);
    expect(stdout).toContain("No data");
  });

  it("query --sql works", async () => {
    const { stdout, exitCode } = await run(["query", "--sql", "SELECT 1 as val"], { cwd: tmpDir });
    expect(exitCode).toBe(0);
    expect(stdout).toContain("1");
  });

  it("revert with no changes", async () => {
    const { output, exitCode } = await run(["revert", "--yes"], { cwd: tmpDir });
    expect(exitCode).toBe(0);
    expect(output).toContain("No pending changes");
  });

  it("push with no changes", async () => {
    const { output, exitCode } = await run(["push", "--yes"], { cwd: tmpDir });
    expect(exitCode).toBe(0);
    expect(output).toContain("No pending changes");
  });
});
