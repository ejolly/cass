/**
 * Validated environment variables — single source of truth for env config.
 */
import { z } from "zod";

const EnvSchema = z.object({
  CANVAS_TOKEN: z.string().optional(),
  GITHUB_TOKEN: z.string().optional(),
});

export const env = EnvSchema.parse(Bun.env);
