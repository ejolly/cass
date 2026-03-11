/**
 * GitHub client — thin Bun.$ wrappers over `gh api --paginate`.
 * Replaces ~150 lines of async httpx client.
 */
import { $ } from "bun";
import type { z } from "zod";

// Use ZodSchema with explicit output type to handle .default() fields correctly
type Schema<T> = z.ZodType<T, z.ZodTypeDef, unknown>;

/** Check if gh CLI is available. */
export async function checkAvailable(): Promise<boolean> {
  try {
    await $`which gh`.quiet();
    return true;
  } catch {
    return false;
  }
}

/** Check if gh is authenticated. Returns [isAuthed, username]. */
export async function checkAuth(): Promise<[boolean, string]> {
  try {
    const result = await $`gh auth status`.quiet();
    const output = result.stderr.toString();
    const match = /Logged in to .+ account (\S+)/.exec(output);
    return [true, match?.[1] ?? ""];
  } catch {
    return [false, ""];
  }
}

/**
 * Call `gh api` with pagination and parse the JSON response.
 */
export async function ghApi<T>(
  endpoint: string,
  schema: Schema<T>,
  options?: { paginate?: boolean },
): Promise<T> {
  const args = ["gh", "api", endpoint];
  if (options?.paginate) args.push("--paginate");

  const result = await $`${args}`.quiet();
  const json = JSON.parse(result.stdout.toString());
  return schema.parse(json);
}

/**
 * Call `gh api` expecting an array response with pagination.
 */
export async function ghApiList<T>(endpoint: string, schema: Schema<T>): Promise<T[]> {
  const args = ["gh", "api", endpoint, "--paginate"];
  const result = await $`${args}`.quiet();
  const stdout = result.stdout.toString().trim();

  if (!stdout) return [];

  const json = JSON.parse(stdout);
  const items = Array.isArray(json) ? json : [json];
  return items.map((item: unknown) => schema.parse(item));
}

/**
 * Call `gh api` for a single resource (no pagination).
 */
export async function ghApiSingle<T>(endpoint: string, schema: Schema<T>): Promise<T> {
  const result = await $`gh api ${endpoint}`.quiet();
  const json = JSON.parse(result.stdout.toString());
  return schema.parse(json);
}

/**
 * Check if a resource exists via gh api (returns true/false, no throw on 404).
 */
export async function ghApiExists(endpoint: string): Promise<boolean> {
  try {
    await $`gh api ${endpoint}`.quiet();
    return true;
  } catch {
    return false;
  }
}
