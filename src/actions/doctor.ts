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
	const checks: Check[] = [];

	// 1. Config file
	const path = await configFilePath();
	if (!path) {
		checks.push(err("cass.toml", "not found in any parent directory"));
		return checks;
	}
	checks.push(ok("cass.toml", path));

	if (!cfg) return checks;

	// 2. Classroom checks
	const state = classroomStatus(cfg);
	await match(state)
		.with({ tag: "configured" }, async (s) => {
			checks.push(ok("classroom", `gh_id=${s.ghId}`, 1));
			await addGHChecks(checks);
		})
		.with({ tag: "pending" }, async (s) => {
			checks.push(warn("classroom", `url_id=${s.urlId} (gh_id unresolved)`, 1));
			await addGHChecks(checks);
		})
		.with({ tag: "missing" }, () => {
			checks.push(warn("classroom", "not configured (optional)", 1));
		})
		.exhaustive();

	// 3. Canvas checks
	if (hasCanvas(cfg)) {
		checks.push(ok("canvas", cfg.canvasBaseUrl, 1));
		checks.push(ok("course_id", String(cfg.canvasCourseId), 2));

		// Check token
		const tokenPath = join(cfg.root, ".canvastoken");
		const tokenExists = await Bun.file(tokenPath).exists();
		const envToken = Boolean(process.env.CANVAS_TOKEN);

		if (tokenExists) {
			checks.push(ok("canvas token", ".canvastoken", 2));
		} else if (envToken) {
			checks.push(ok("canvas token", "$CANVAS_TOKEN", 2));
		} else {
			checks.push(err("canvas token", "not found (.canvastoken or $CANVAS_TOKEN)", 2));
		}
	} else {
		checks.push(warn("canvas", "not configured", 1));
	}

	return checks;
}

async function addGHChecks(checks: Check[]): Promise<void> {
	const ghAvailable = await checkAvailable();
	if (!ghAvailable) {
		checks.push(err("gh CLI", "not found", 2));
		return;
	}
	checks.push(ok("gh CLI", "available", 2));

	const [authed, username] = await checkAuth();
	if (authed) {
		checks.push(ok("gh auth", username, 2));
	} else {
		checks.push(err("gh auth", "not authenticated", 2));
	}
}
