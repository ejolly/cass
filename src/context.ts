import type { Config } from "@/actions/config.ts";
import type { Database } from "@/db/schema.ts";
/**
 * Application context — lightweight dependency injection for commands.
 * Replaces singleton patterns with explicit dependency passing.
 */
import type { KyInstance } from "ky";
import type { Kysely } from "kysely";

export interface AppContext {
  config: Config;
  db: Kysely<Database>;
  canvasClient: KyInstance | null;
}

/** Create a full application context from config. */
export async function createContext(config: Config): Promise<AppContext> {
  const { join } = await import("node:path");
  const { createDb } = await import("@/db/connection.ts");
  const { up } = await import("@/db/migrations/001_initial.ts");

  const dbFile = join(config.root, "cass.db");
  const db = createDb(dbFile);

  // Ensure schema exists
  try {
    await up(db as import("kysely").Kysely<unknown>);
  } catch {
    // Migration already applied
  }

  // Canvas client (optional)
  let canvasClient: KyInstance | null = null;
  const { hasCanvas } = await import("@/actions/config.ts");
  if (hasCanvas(config)) {
    try {
      const { loadCanvasToken, createCanvasClient } = await import("@/apis/canvas/client.ts");
      const token = await loadCanvasToken(config.root);
      canvasClient = createCanvasClient({ baseUrl: config.canvasBaseUrl, token });
    } catch {
      // Canvas token not available — client stays null
    }
  }

  return { config, db, canvasClient };
}

/** Destroy context resources. */
export async function destroyContext(ctx: AppContext): Promise<void> {
  await ctx.db.destroy();
}
