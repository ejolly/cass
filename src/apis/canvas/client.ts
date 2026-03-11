/**
 * Canvas API client — ky instance with retry hooks + pagination helper.
 * Replaces ~230 lines of Python (RetryTransport + CanvasClient).
 */
import { join } from "node:path";
import { ApiError, ConfigError, NotFoundError } from "@/errors.ts";
import ky, { type KyInstance, type AfterResponseHook } from "ky";
import { match } from "ts-pattern";
import { CanvasProgress } from "./schema.ts";

const THROTTLE_THRESHOLD = 50;
const THROTTLE_DELAY_MS = 1000;
const LINK_NEXT_RE = /<([^>]+)>;\s*rel="next"/;

/** Proactive throttle: sleep when rate limit remaining is low. */
const throttleOnRateLimit: AfterResponseHook = async (_request, _options, response) => {
  const remaining = response.headers.get("X-Rate-Limit-Remaining");
  if (remaining && Number.parseFloat(remaining) < THROTTLE_THRESHOLD) {
    await Bun.sleep(THROTTLE_DELAY_MS);
  }
};

export interface CanvasClientOptions {
  baseUrl: string;
  token: string;
}

export function createCanvasClient(opts: CanvasClientOptions): KyInstance {
  const prefixUrl = `${opts.baseUrl.replace(/\/+$/, "")}/api/v1`;

  return ky.create({
    prefixUrl,
    headers: {
      Authorization: `Bearer ${opts.token}`,
    },
    timeout: 30_000,
    retry: {
      limit: 3,
      backoffLimit: 8000,
    },
    hooks: {
      afterResponse: [throttleOnRateLimit],
    },
  });
}

/**
 * Follow Canvas Link-header pagination.
 * Returns all pages concatenated into a single array.
 */
export async function getPaginated<T>(
  client: KyInstance,
  endpoint: string,
  params: Record<string, string | number> = {},
): Promise<T[]> {
  const allResults: T[] = [];
  const searchParams = new URLSearchParams();
  searchParams.set("per_page", "100");
  for (const [k, v] of Object.entries(params)) {
    searchParams.set(k, String(v));
  }

  let url: string | null = `${endpoint}?${searchParams.toString()}`;

  while (url) {
    const response = await client.get(url);
    const data = await response.json<T | T[]>();

    if (Array.isArray(data)) {
      allResults.push(...data);
    } else {
      allResults.push(data);
    }

    // Parse Link header for next page
    const linkHeader = response.headers.get("Link");
    if (linkHeader) {
      const linkMatch = LINK_NEXT_RE.exec(linkHeader);
      if (linkMatch?.[1]) {
        // Canvas returns absolute URLs; extract path + query to keep relative
        const nextUrl = linkMatch[1];
        if (nextUrl.startsWith("http")) {
          const parsed = new URL(nextUrl);
          url = `${parsed.pathname.replace(/^\/api\/v1\//, "")}${parsed.search}`;
        } else {
          url = nextUrl;
        }
      } else {
        url = null;
      }
    } else {
      url = null;
    }
  }

  return allResults;
}

/**
 * Wait for a Canvas async progress to complete.
 * Uses ts-pattern for exhaustive state matching.
 */
export async function waitForProgress(
  client: KyInstance,
  progressId: number,
  timeoutMs = 120_000,
): Promise<CanvasProgress> {
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    const raw = await client.get(`progress/${progressId}`).json();
    const progress = CanvasProgress.parse(raw);

    const result = match(progress.workflow_state)
      .with("completed", () => ({ done: true as const, progress }))
      .with("failed", () => {
        throw new ApiError(`Canvas progress failed: ${progress.message ?? "unknown error"}`);
      })
      .with("queued", "running", () => ({ done: false as const }))
      .exhaustive();

    if (result.done) return result.progress;

    await Bun.sleep(1000);
  }

  throw new ApiError(`Canvas progress ${progressId} timed out after ${timeoutMs}ms`);
}

/**
 * Resolve a Canvas resource by numeric ID or case-insensitive name.
 * Works for modules, assignments, quizzes.
 */
export async function resolveResource<T extends { id: number; name?: string; title?: string }>(
  items: T[],
  identifier: string,
): Promise<T> {
  // Try numeric ID first
  const numId = Number(identifier);
  if (!Number.isNaN(numId)) {
    const byId = items.find((item) => item.id === numId);
    if (byId) return byId;
  }

  // Fall back to case-insensitive name match
  const lower = identifier.toLowerCase();
  const byName = items.find(
    (item) => item.name?.toLowerCase() === lower || item.title?.toLowerCase() === lower,
  );

  if (!byName) {
    throw new NotFoundError("resource", identifier);
  }

  return byName;
}

/**
 * Load Canvas token from .canvastoken file or CANVAS_TOKEN env var.
 */
export async function loadCanvasToken(projectRoot: string): Promise<string> {
  const tokenPath = join(projectRoot, ".canvastoken");
  const tokenFile = Bun.file(tokenPath);

  if (await tokenFile.exists()) {
    const token = (await tokenFile.text()).trim();
    if (token) return token;
  }

  const { env } = await import("@/env.ts");
  const envToken = env.CANVAS_TOKEN;
  if (envToken) return envToken.trim();

  throw new ConfigError(
    "Canvas token not found. Create a .canvastoken file or set CANVAS_TOKEN env var.",
  );
}
