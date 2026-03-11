/**
 * Config loading — smol-toml parsing + zod validated config.
 */
import { dirname, join } from "node:path";
import { parse as parseTOML, stringify as stringifyTOML } from "smol-toml";
import { z } from "zod";

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
	// Database
	motherduckDb: string;
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

export function findProjectRoot(start = process.cwd()): string | null {
	let dir = start;
	while (true) {
		const candidate = join(dir, "cass.toml");
		if (Bun.file(candidate).size > 0) return dir;
		const parent = dirname(dir);
		if (parent === dir) return null;
		dir = parent;
	}
}

export function configFilePath(): string | null {
	const root = findProjectRoot();
	return root ? join(root, "cass.toml") : null;
}

// ─── Loading ────────────────────────────────────────────────────────

let _cached: Config | null = null;

export async function loadConfig(): Promise<Config> {
	const root = findProjectRoot();
	if (!root) throw new Error("Could not find cass.toml in any parent directory");

	const tomlPath = join(root, "cass.toml");
	const text = await Bun.file(tomlPath).text();
	const data = parseTOML(text);

	const canvas = (data.canvas ?? {}) as Record<string, unknown>;
	const classroom = (data.classroom ?? {}) as Record<string, unknown>;
	const database = (data.database ?? {}) as Record<string, unknown>;

	return {
		root,
		classroomUrl: String(classroom.url ?? ""),
		classroomUrlId: Number(classroom.url_id ?? 0),
		classroomGhId: Number(classroom.gh_id ?? 0),
		classroomSlug: String(classroom.slug ?? ""),
		classroomTitle: String(classroom.title ?? ""),
		org: String(classroom.org ?? ""),
		canvasBaseUrl: String(canvas.base_url ?? ""),
		canvasCourseId: Number(canvas.course_id ?? 0),
		canvasModules: Array.isArray(canvas.modules)
			? canvas.modules.map((m: unknown) => CanvasModuleSpec.parse(m))
			: [],
		canvasAssignments: Array.isArray(canvas.assignments)
			? canvas.assignments.map((a: unknown) => CanvasAssignmentSpec.parse(a))
			: [],
		motherduckDb: String(database.motherduck ?? ""),
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

export async function updateConfig(path: string, updates: ConfigUpdate): Promise<void> {
	const text = await Bun.file(path).text();
	const data = parseTOML(text) as Record<string, Record<string, unknown>>;

	if (!data.classroom) data.classroom = {};
	if (!data.canvas) data.canvas = {};

	if (updates.classroomUrl !== undefined) data.classroom.url = updates.classroomUrl;
	if (updates.classroomUrlId !== undefined) data.classroom.url_id = updates.classroomUrlId;
	if (updates.classroomGhId !== undefined) data.classroom.gh_id = updates.classroomGhId;
	if (updates.classroomSlug !== undefined) data.classroom.slug = updates.classroomSlug;
	if (updates.classroomTitle !== undefined) data.classroom.title = updates.classroomTitle;
	if (updates.org !== undefined) data.classroom.org = updates.org;
	if (updates.canvasBaseUrl !== undefined) data.canvas.base_url = updates.canvasBaseUrl;
	if (updates.canvasCourseId !== undefined) data.canvas.course_id = updates.canvasCourseId;

	await Bun.write(path, stringifyTOML(data));
	resetConfig();
}
