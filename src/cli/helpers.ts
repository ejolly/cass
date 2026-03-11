/**
 * Shared CLI helpers — config/db/client bootstrapping for command handlers.
 */
import type { Config } from "@/actions/config.ts";
import type { Database } from "@/db/schema.ts";
import type { Kysely } from "kysely";

export async function requireConfig(): Promise<Config> {
  const { getConfig } = await import("@/actions/config.ts");
  return getConfig();
}

export async function requireDb(cfg: Config): Promise<Kysely<Database>> {
  const { createDb } = await import("@/db/connection.ts");
  const { join } = await import("node:path");
  const dbFile = join(cfg.root, "cass.db");
  const file = Bun.file(dbFile);
  if (!(await file.exists())) {
    throw new Error(`Database not found: ${dbFile}\nRun 'cassa pull' first.`);
  }
  return createDb(dbFile);
}

export async function requireConfigWithCanvas(): Promise<Config> {
  const { getConfig, hasCanvas } = await import("@/actions/config.ts");
  const cfg = await getConfig();
  if (!hasCanvas(cfg)) {
    const consola = (await import("consola")).default;
    consola.error("Canvas not configured in cass.toml");
    process.exit(1);
  }
  return cfg;
}

export async function createCanvasClient(cfg: Config) {
  const { hasCanvas } = await import("@/actions/config.ts");
  if (!hasCanvas(cfg)) return null;
  const { loadCanvasToken, createCanvasClient: create } = await import("@/apis/canvas/client.ts");
  const token = await loadCanvasToken(cfg.root);
  return create({ baseUrl: cfg.canvasBaseUrl, token });
}

export async function getCanvasClient(cfg: Config) {
  const { loadCanvasToken, createCanvasClient } = await import("@/apis/canvas/client.ts");
  const token = await loadCanvasToken(cfg.root);
  return createCanvasClient({ baseUrl: cfg.canvasBaseUrl, token });
}

export type { OutputFormat } from "@/cli/report.ts";
