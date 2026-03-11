/**
 * Prerequisite checks — reports config, CLI tools, and auth status.
 */
import { join } from "node:path";
import { match } from "ts-pattern";
import { checkAuth, checkAvailable } from "../apis/github/client.ts";
import { type Config, classroomStatus, configFilePath, hasCanvas } from "./config.ts";

export type CheckStatus = "ok" | "warn" | "error";

export interface Check {
	name: string;
	status: CheckStatus;
	detail: string;
	indent: number;
}

function ok(name: string, detail: string, indent = 0): Check {
	return { name, status: "ok", detail, indent };
}

function warn(name: string, detail: string, indent = 0): Check {
	return { name, status: "warn", detail, indent };
}

function err(name: string, detail: string, indent = 0): Check {
	return { name, status: "error", detail, indent };
}

/** Run all prerequisite checks and return results. */
export async function checkPrerequisites(cfg?: Config): Promise<Check[]> {
	const path = await configFilePath();
	if (!path) return [err("cass.toml", "not found in any parent directory")];
	if (!cfg) return [ok("cass.toml", path)];

	return [ok("cass.toml", path), ...(await classroomChecks(cfg)), ...(await canvasChecks(cfg))];
}

async function classroomChecks(cfg: Config): Promise<Check[]> {
	return match(classroomStatus(cfg))
		.with({ tag: "configured" }, async (s) => [
			ok("classroom", `gh_id=${s.ghId}`, 1),
			...(await ghToolChecks()),
		])
		.with({ tag: "pending" }, async (s) => [
			warn("classroom", `url_id=${s.urlId} (gh_id unresolved)`, 1),
			...(await ghToolChecks()),
		])
		.with({ tag: "missing" }, () => [warn("classroom", "not configured (optional)", 1)])
		.exhaustive();
}

async function ghToolChecks(): Promise<Check[]> {
	const ghAvailable = await checkAvailable();
	if (!ghAvailable) return [err("gh CLI", "not found", 2)];

	const [authed, username] = await checkAuth();
	return [
		ok("gh CLI", "available", 2),
		authed ? ok("gh auth", username, 2) : err("gh auth", "not authenticated", 2),
	];
}

async function canvasChecks(cfg: Config): Promise<Check[]> {
	if (!hasCanvas(cfg)) return [warn("canvas", "not configured", 1)];

	const tokenPath = join(cfg.root, ".canvastoken");
	const tokenExists = await Bun.file(tokenPath).exists();
	const envToken = Boolean(process.env.CANVAS_TOKEN);

	const tokenCheck = tokenExists
		? ok("canvas token", ".canvastoken", 2)
		: envToken
			? ok("canvas token", "$CANVAS_TOKEN", 2)
			: err("canvas token", "not found (.canvastoken or $CANVAS_TOKEN)", 2);

	return [
		ok("canvas", cfg.canvasBaseUrl, 1),
		ok("course_id", String(cfg.canvasCourseId), 2),
		tokenCheck,
	];
}
