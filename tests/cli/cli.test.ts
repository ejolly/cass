import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { run, useProjectDir } from "./helpers.ts";

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
});

describe("commands with project", () => {
  const getDir = useProjectDir();

  it("status shows config info", async () => {
    const { output, exitCode } = await run(["status"], { cwd: getDir() });
    expect(exitCode).toBe(0);
    expect(output).toContain("canvas.test.edu");
  });

  it("query fails without DB", async () => {
    const result = await run(["query", "students"], { cwd: getDir() });
    expect(result.exitCode).not.toBe(0);
  });

  it("delete --yes succeeds even without DB", async () => {
    const { exitCode } = await run(["delete", "--yes"], { cwd: getDir() });
    expect(exitCode).toBe(0);
  });

  it("backup --list works with no backups", async () => {
    const { output, exitCode } = await run(["backup", "--list"], { cwd: getDir() });
    expect(exitCode).toBe(0);
    expect(output).toContain("No backups");
  });
});

describe("commands with DB", () => {
  const getDir = useProjectDir({ withDb: true });

  it("query students returns empty table", async () => {
    const { stdout, exitCode } = await run(["query", "students"], { cwd: getDir() });
    expect(exitCode).toBe(0);
    expect(stdout).toContain("No data");
  });

  it("query --sql works", async () => {
    const { stdout, exitCode } = await run(["query", "--sql", "SELECT 1 as val"], {
      cwd: getDir(),
    });
    expect(exitCode).toBe(0);
    expect(stdout).toContain("1");
  });

  it("revert with no changes", async () => {
    const { output, exitCode } = await run(["revert", "--yes"], { cwd: getDir() });
    expect(exitCode).toBe(0);
    expect(output).toContain("No pending changes");
  });

  it("push with no changes", async () => {
    const { output, exitCode } = await run(["push", "--yes"], { cwd: getDir() });
    expect(exitCode).toBe(0);
    expect(output).toContain("No pending changes");
  });
});
