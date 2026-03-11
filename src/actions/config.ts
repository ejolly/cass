/**
 * Config loading — smol-toml parsing + zod validated config.
 */
import { join } from "node:path";
import { parse as parseTOML, stringify as stringifyTOML } from "smol-toml";
import { z } from "zod";
import { findProjectRoot } from "../utils/paths.ts";

// ─── Config schema ──────────────────────────────────────────────────

const CanvasModuleSpec = z.object({
  name: z.string(),
  published: z.boolean().default(false),
});

const CanvasAssignmentSpec = z.object({
  name: z.string(),
  points: z.number().default(0),
  submission_types: z.array(z.string()).default(["online_url"]),
  due_at: z.string().default(""),
  published: z.boolean().default(false),
  group: z.string().default(""),
});

const TomlConfigSchema = z.object({
  classroom: z
    .object({
      url: z.coerce.string().default(""),
      url_id: z.coerce.number().default(0),
      gh_id: z.coerce.number().default(0),
      slug: z.coerce.string().default(""),
      title: z.coerce.string().default(""),
      org: z.coerce.string().default(""),
    })
    .default({}),
  canvas: z
    .object({
      base_url: z.coerce.string().default(""),
      course_id: z.coerce.number().default(0),
      modules: z.array(CanvasModuleSpec).default([]),
      assignments: z.array(CanvasAssignmentSpec).default([]),
    })
    .default({}),
});

export type CanvasModuleSpec = z.infer<typeof CanvasModuleSpec>;
export type CanvasAssignmentSpec = z.infer<typeof CanvasAssignmentSpec>;

export interface Config {
  root: string;
  // Classroom
  classroomUrl: string;
  classroomUrlId: number;
  classroomGhId: number;
  classroomSlug: string;
  classroomTitle: string;
  org: string;
  // Canvas
  canvasBaseUrl: string;
  canvasCourseId: number;
  canvasModules: CanvasModuleSpec[];
  canvasAssignments: CanvasAssignmentSpec[];
}

export type ConfigState =
  | { tag: "configured"; ghId: number }
  | { tag: "pending"; url: string; urlId: number }
  | { tag: "missing" };

// ─── Computed properties ────────────────────────────────────────────

export function hasClassroomUrl(cfg: Config): boolean {
  return Boolean(cfg.classroomUrl && cfg.classroomUrlId);
}

export function hasClassroom(cfg: Config): boolean {
  return hasClassroomUrl(cfg) && cfg.classroomGhId > 0;
}

export function classroomNeedsResolution(cfg: Config): boolean {
  return hasClassroomUrl(cfg) && !hasClassroom(cfg);
}

export function classroomStatus(cfg: Config): ConfigState {
  if (hasClassroom(cfg)) return { tag: "configured", ghId: cfg.classroomGhId };
  if (hasClassroomUrl(cfg))
    return { tag: "pending", url: cfg.classroomUrl, urlId: cfg.classroomUrlId };
  return { tag: "missing" };
}

export function hasCanvas(cfg: Config): boolean {
  return Boolean(cfg.canvasBaseUrl && cfg.canvasCourseId);
}

// ─── URL parsing ────────────────────────────────────────────────────

export function parseCanvasCourseUrl(raw: string): [string, number] | null {
  const m = /^(https?:\/\/[^/]+)\/courses\/(\d+)/.exec(raw.trim());
  if (!m?.[1] || !m[2]) return null;
  return [m[1], Number.parseInt(m[2], 10)];
}

export function parseClassroomUrl(raw: string): number | null {
  const m = /classrooms\/(\d+)/.exec(raw.trim());
  if (!m?.[1]) return null;
  return Number.parseInt(m[1], 10);
}

// ─── File discovery ─────────────────────────────────────────────────

export { findProjectRoot };

export async function configFilePath(): Promise<string | null> {
  const root = await findProjectRoot();
  return root ? join(root, "cass.toml") : null;
}

// ─── Loading ────────────────────────────────────────────────────────

let _cached: Config | null = null;

export async function loadConfig(): Promise<Config> {
  const root = await findProjectRoot();
  if (!root) throw new Error("Could not find cass.toml in any parent directory");

  const tomlPath = join(root, "cass.toml");
  const text = await Bun.file(tomlPath).text();
  const parsed = TomlConfigSchema.parse(parseTOML(text));

  return {
    root,
    classroomUrl: parsed.classroom.url,
    classroomUrlId: parsed.classroom.url_id,
    classroomGhId: parsed.classroom.gh_id,
    classroomSlug: parsed.classroom.slug,
    classroomTitle: parsed.classroom.title,
    org: parsed.classroom.org,
    canvasBaseUrl: parsed.canvas.base_url,
    canvasCourseId: parsed.canvas.course_id,
    canvasModules: parsed.canvas.modules,
    canvasAssignments: parsed.canvas.assignments,
  };
}

export async function getConfig(): Promise<Config> {
  if (!_cached) _cached = await loadConfig();
  return _cached;
}

export function resetConfig(): void {
  _cached = null;
}

// ─── Writing ────────────────────────────────────────────────────────

export interface ConfigUpdate {
  classroomUrl?: string;
  classroomUrlId?: number;
  classroomGhId?: number;
  classroomSlug?: string;
  classroomTitle?: string;
  org?: string;
  canvasBaseUrl?: string;
  canvasCourseId?: number;
}

/** Map from ConfigUpdate keys to their TOML section + field name. */
const UPDATE_FIELD_MAP: Record<keyof ConfigUpdate, [string, string]> = {
  classroomUrl: ["classroom", "url"],
  classroomUrlId: ["classroom", "url_id"],
  classroomGhId: ["classroom", "gh_id"],
  classroomSlug: ["classroom", "slug"],
  classroomTitle: ["classroom", "title"],
  org: ["classroom", "org"],
  canvasBaseUrl: ["canvas", "base_url"],
  canvasCourseId: ["canvas", "course_id"],
};

export async function updateConfig(path: string, updates: ConfigUpdate): Promise<void> {
  const text = await Bun.file(path).text();
  const data = parseTOML(text) as Record<string, Record<string, unknown>>;

  for (const [key, value] of Object.entries(updates)) {
    if (value === undefined) continue;
    const [section, field] = UPDATE_FIELD_MAP[key as keyof ConfigUpdate]!;
    if (!data[section]) data[section] = {};
    data[section]![field] = value;
  }

  await Bun.write(path, stringifyTOML(data));
  resetConfig();
}
