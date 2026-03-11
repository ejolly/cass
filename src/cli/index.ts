/**
 * Root CLI commands — status, init, pull, push, revert, query, pull-repos, delete, backup, restore.
 */
import type { CAC } from "cac";
import consola from "consola";
import { match } from "ts-pattern";

import type { Config } from "../actions/config.ts";
import { type OutputFormat, formatRows, formatTable } from "./report.ts";

// ─── Shared helpers ──────────────────────────────────────────────────

async function requireConfig(): Promise<Config> {
	const { getConfig } = await import("../actions/config.ts");
	return getConfig();
}

async function requireDb(cfg: Config) {
	const { createDb } = await import("../db/connection.ts");
	const { join } = await import("node:path");
	const dbFile = join(cfg.root, "cass.db");
	const file = Bun.file(dbFile);
	if (!(await file.exists())) {
		throw new Error(`Database not found: ${dbFile}\nRun 'cassa pull' first.`);
	}
	return createDb(dbFile);
}

async function createCanvasClient(cfg: Config) {
	const { hasCanvas } = await import("../actions/config.ts");
	if (!hasCanvas(cfg)) return null;
	const { loadCanvasToken, createCanvasClient: create } = await import("../apis/canvas/client.ts");
	const token = await loadCanvasToken(cfg.root);
	return create({ baseUrl: cfg.canvasBaseUrl, token });
}

// ─── Command registration ────────────────────────────────────────────

export function registerRootCommands(cli: CAC): void {
	// ── status ──
	cli.command("status", "Show project status").action(async () => {
		const cfg = await requireConfig();
		const { join } = await import("node:path");

		consola.box(`cassa — ${cfg.canvasBaseUrl || "no Canvas"}`);

		// Config summary
		consola.info(`Root: ${cfg.root}`);
		if (cfg.canvasBaseUrl) {
			consola.info(`Canvas: ${cfg.canvasBaseUrl}/courses/${cfg.canvasCourseId}`);
		}
		if (cfg.classroomGhId) {
			consola.info(
				`Classroom: ${cfg.classroomTitle || cfg.classroomSlug} (gh_id=${cfg.classroomGhId})`,
			);
		} else if (cfg.classroomUrl) {
			consola.info(`Classroom: ${cfg.classroomUrl} (pending resolution)`);
		}

		// DB summary
		const dbFile = join(cfg.root, "cass.db");
		if (!(await Bun.file(dbFile).exists())) {
			consola.warn("No database found. Run 'cassa pull' to fetch data.");
			return;
		}

		const { createDb } = await import("../db/connection.ts");
		const db = createDb(dbFile);
		try {
			const students = await db
				.selectFrom("students")
				.select(db.fn.countAll().as("count"))
				.executeTakeFirstOrThrow();
			const assignments = await db
				.selectFrom("assignments")
				.select(db.fn.countAll().as("count"))
				.executeTakeFirstOrThrow();
			const submissions = await db
				.selectFrom("canvas_submissions")
				.select(db.fn.countAll().as("count"))
				.executeTakeFirstOrThrow();

			consola.info(
				`Students: ${students.count}, Assignments: ${assignments.count}, Submissions: ${submissions.count}`,
			);

			// Pending changes
			const { getPendingGradeChanges, getPendingAssignmentChanges } = await import("../db/sync.ts");
			const pendingGrades = await getPendingGradeChanges(db);
			const pendingAssignments = await getPendingAssignmentChanges(db);

			if (pendingGrades.length > 0 || pendingAssignments.length > 0) {
				consola.warn(
					`Pending changes: ${pendingGrades.length} grade(s), ${pendingAssignments.length} assignment(s)`,
				);
			} else {
				consola.success("No pending changes");
			}
		} finally {
			await db.destroy();
		}
	});

	// ── init ──
	cli.command("init", "Interactive project setup").action(async () => {
		const prompts = await import("@clack/prompts");
		const { configFilePath, parseCanvasCourseUrl, parseClassroomUrl, updateConfig } = await import(
			"../actions/config.ts"
		);

		prompts.intro("cassa init");

		// Find or create cass.toml
		let cfgPath = await configFilePath();
		if (!cfgPath) {
			const { join } = await import("node:path");
			cfgPath = join(process.cwd(), "cass.toml");
			await Bun.write(cfgPath, "");
			consola.info(`Created ${cfgPath}`);
		}

		// Canvas URL
		const canvasUrl = await prompts.text({
			message: "Canvas course URL",
			placeholder: "https://canvas.ucsd.edu/courses/12345",
			validate: (val) => {
				if (!val) return "URL is required";
				if (!parseCanvasCourseUrl(val)) return "Invalid Canvas course URL";
			},
		});
		if (prompts.isCancel(canvasUrl)) {
			prompts.cancel();
			process.exit(0);
		}

		const [baseUrl, courseId] = parseCanvasCourseUrl(canvasUrl as string)!;

		// Canvas token
		const canvasToken = await prompts.text({
			message: "Canvas API token",
			placeholder: "paste your token here",
		});
		if (prompts.isCancel(canvasToken)) {
			prompts.cancel();
			process.exit(0);
		}

		if (canvasToken) {
			const { join } = await import("node:path");
			const { dirname } = await import("node:path");
			const tokenPath = join(dirname(cfgPath), ".canvastoken");
			await Bun.write(tokenPath, (canvasToken as string).trim());
			consola.success("Saved .canvastoken");
		}

		// GitHub Classroom URL (optional)
		const classroomUrl = await prompts.text({
			message: "GitHub Classroom URL (optional, press Enter to skip)",
			placeholder: "https://classroom.github.com/classrooms/...",
		});

		const updates: Record<string, unknown> = {
			canvasBaseUrl: baseUrl,
			canvasCourseId: courseId,
		};

		if (classroomUrl && !prompts.isCancel(classroomUrl)) {
			const urlId = parseClassroomUrl(classroomUrl as string);
			if (urlId) {
				updates.classroomUrl = classroomUrl;
				updates.classroomUrlId = urlId;

				// Try to resolve gh_id
				try {
					const { ghApiList } = await import("../apis/github/client.ts");
					const { z } = await import("zod");
					const ClassroomSchema = z.object({ id: z.number(), name: z.string(), url: z.string() });
					const classrooms = await ghApiList("classrooms", ClassroomSchema);
					const found = classrooms.find(
						(c: { id: number; name: string; url: string }) =>
							(classroomUrl as string).includes(String(c.id)) ||
							(classroomUrl as string).includes(c.name),
					);
					if (found) {
						updates.classroomGhId = found.id;
						updates.classroomTitle = found.name;
						consola.success(`Resolved classroom: ${found.name} (id=${found.id})`);
					} else {
						consola.warn("Classroom URL saved but gh_id could not be resolved");
					}
				} catch {
					consola.warn("Could not resolve classroom (gh CLI unavailable?)");
				}
			} else {
				consola.warn("Invalid classroom URL, skipping");
			}
		}

		await updateConfig(cfgPath, updates as never);
		consola.success(`Config saved to ${cfgPath}`);

		// Run doctor
		const { getConfig } = await import("../actions/config.ts");
		const { checkPrerequisites } = await import("../actions/doctor.ts");
		const cfg = await getConfig();
		const checks = await checkPrerequisites(cfg);
		for (const c of checks) {
			const prefix = "  ".repeat(c.indent);
			match(c.status)
				.with("ok", () => consola.success(`${prefix}${c.name}: ${c.detail}`))
				.with("warn", () => consola.warn(`${prefix}${c.name}: ${c.detail}`))
				.with("error", () => consola.error(`${prefix}${c.name}: ${c.detail}`))
				.exhaustive();
		}

		prompts.outro("Setup complete!");
	});

	// ── pull ──
	cli
		.command("pull", "Fetch data from APIs into local DB")
		.option("--students", "Pull students only")
		.option("--assignments", "Pull assignments only")
		.option("--submissions", "Pull submissions only")
		.action(async (opts: { students?: boolean; assignments?: boolean; submissions?: boolean }) => {
			const cfg = await requireConfig();
			const { join } = await import("node:path");
			const { createDb } = await import("../db/connection.ts");
			const { up } = await import("../../migrations/001_initial.ts");
			const { pullAll, pullStudents, pullAssignments, pullSubmissions } = await import(
				"../actions/pull.ts"
			);
			const { snapshotGradesSynced, snapshotAssignmentsSynced } = await import("../db/sync.ts");

			const dbFile = join(cfg.root, "cass.db");
			const db = createDb(dbFile);

			// Ensure schema exists
			try {
				await up(db as import("kysely").Kysely<unknown>);
			} catch {
				// Migration already applied
			}

			const client = await createCanvasClient(cfg);
			const progress = (step: string, detail: string) => consola.info(`[${step}] ${detail}`);

			try {
				const selective = opts.students || opts.assignments || opts.submissions;
				if (!selective) {
					await pullAll(db, client, cfg, progress);
				} else {
					if (opts.students) await pullStudents(db, client, cfg, progress);
					if (opts.assignments) await pullAssignments(db, client, cfg, progress);
					if (opts.submissions) await pullSubmissions(db, client, cfg, progress);
					// Snapshot synced state after selective pull too
					await snapshotGradesSynced(db);
					await snapshotAssignmentsSynced(db);
				}
				consola.success("Pull complete");
			} finally {
				await db.destroy();
			}
		});

	// ── push ──
	cli
		.command("push", "Push pending changes to Canvas")
		.option("--yes, -y", "Skip confirmation")
		.action(async (opts: { yes?: boolean }) => {
			const cfg = await requireConfig();
			const db = await requireDb(cfg);
			const { getPendingGradeChanges, getPendingAssignmentChanges } = await import("../db/sync.ts");
			const { snapshotGradesSynced, snapshotAssignmentsSynced } = await import("../db/sync.ts");

			try {
				const pendingGrades = await getPendingGradeChanges(db);
				const pendingAssignments = await getPendingAssignmentChanges(db);

				if (pendingGrades.length === 0 && pendingAssignments.length === 0) {
					consola.info("No pending changes to push");
					return;
				}

				const { buildGradePushData, buildPushPreview, pushGrades } = await import(
					"../apis/canvas/sync.ts"
				);

				// Build grade push data
				const [gradeData, skipped] = buildGradePushData(pendingGrades);
				const preview = await buildPushPreview(db, gradeData);

				// Show preview
				consola.info(
					`${pendingGrades.length} grade change(s), ${pendingAssignments.length} assignment change(s)`,
				);
				if (skipped > 0) consola.warn(`${skipped} grade(s) skipped (invalid)`);

				if (preview.length > 0) {
					const rows = preview.map((p) => ({
						Assignment: p.name,
						Grades: p.count,
						"Manual Post": p.postManually ? "yes" : "",
					}));
					console.log(formatTable(rows, { title: "Grade Push Preview" }));
				}

				if (!opts.yes) {
					const prompts = await import("@clack/prompts");
					const confirm = await prompts.confirm({ message: "Push changes?" });
					if (prompts.isCancel(confirm) || !confirm) {
						consola.info("Cancelled");
						return;
					}
				}

				const client = await createCanvasClient(cfg);
				if (!client) {
					consola.error("Canvas not configured");
					process.exit(1);
				}

				// Push grades
				if (Object.keys(gradeData).length > 0) {
					const results = await pushGrades(client, cfg.canvasCourseId, gradeData);
					for (const r of results) {
						if (r.ok) {
							consola.success(`Assignment ${r.canvasAssignmentId}: ${r.count} grade(s) pushed`);
						} else {
							consola.error(`Assignment ${r.canvasAssignmentId}: ${r.error}`);
						}
					}
				}

				// Snapshot after push
				await snapshotGradesSynced(db);
				await snapshotAssignmentsSynced(db);
				consola.success("Push complete");
			} finally {
				await db.destroy();
			}
		});

	// ── revert ──
	cli
		.command("revert", "Revert pending changes to last synced state")
		.option("--yes, -y", "Skip confirmation")
		.action(async (opts: { yes?: boolean }) => {
			const cfg = await requireConfig();
			const db = await requireDb(cfg);
			const {
				getPendingGradeChanges,
				getPendingAssignmentChanges,
				revertGrades,
				revertAssignments,
			} = await import("../db/sync.ts");

			try {
				const pendingGrades = await getPendingGradeChanges(db);
				const pendingAssignments = await getPendingAssignmentChanges(db);

				if (pendingGrades.length === 0 && pendingAssignments.length === 0) {
					consola.info("No pending changes to revert");
					return;
				}

				consola.info(
					`${pendingGrades.length} grade change(s), ${pendingAssignments.length} assignment change(s)`,
				);

				if (!opts.yes) {
					const prompts = await import("@clack/prompts");
					const confirm = await prompts.confirm({ message: "Revert all pending changes?" });
					if (prompts.isCancel(confirm) || !confirm) {
						consola.info("Cancelled");
						return;
					}
				}

				const revertedG = await revertGrades(db);
				const revertedA = await revertAssignments(db);
				consola.success(`Reverted ${revertedG} grade(s), ${revertedA} assignment(s)`);
			} finally {
				await db.destroy();
			}
		});

	// ── query ──
	cli
		.command("query [dataset]", "Query datasets (students, assignments, submissions, gradebook)")
		.option("--where <expr>", "Filter expression")
		.option("--order <expr>", "Order expression")
		.option("--limit <n>", "Limit rows", { default: 0 })
		.option("--sql <query>", "Raw SQL query")
		.option("--csv", "Output as CSV")
		.option("--save <path>", "Save as markdown file")
		.action(
			async (
				dataset: string | undefined,
				opts: {
					where?: string;
					order?: string;
					limit?: number;
					sql?: string;
					csv?: boolean;
					save?: string;
				},
			) => {
				const cfg = await requireConfig();
				const db = await requireDb(cfg);

				try {
					let rows: Record<string, unknown>[];

					if (opts.sql) {
						const { rawQuery } = await import("../db/introspection.ts");
						rows = await rawQuery(db, opts.sql);
					} else if (dataset) {
						const { queryDataset } = await import("../db/queries.ts");
						const validDatasets = ["students", "assignments", "submissions", "gradebook"] as const;
						if (!validDatasets.includes(dataset as (typeof validDatasets)[number])) {
							consola.error(`Unknown dataset: ${dataset}. Use: ${validDatasets.join(", ")}`);
							process.exit(1);
						}
						rows = await queryDataset(db, dataset as (typeof validDatasets)[number], {
							where: opts.where,
							order: opts.order,
							limit: opts.limit || undefined,
						});
					} else {
						consola.error("Provide a dataset name or --sql query");
						process.exit(1);
					}

					const format: OutputFormat = opts.csv ? "csv" : opts.save ? "markdown" : "table";
					const output = formatRows(rows, { format, title: dataset });

					if (opts.save) {
						await Bun.write(opts.save, `# ${dataset ?? "query"}\n\n${output}\n`);
						consola.success(`Saved to ${opts.save}`);
					} else {
						console.log(output);
					}
				} finally {
					await db.destroy();
				}
			},
		);

	// ── pull-repos ──
	cli
		.command("pull-repos", "Clone/update GitHub repos")
		.option("-a, --assignment <slug>", "Specific assignment slug")
		.option("-s, --limit-students <n>", "Max students", { default: 0 })
		.option("-n, --limit-assignments <n>", "Max assignments", { default: 0 })
		.action(
			async (opts: { assignment?: string; limitStudents?: number; limitAssignments?: number }) => {
				const cfg = await requireConfig();
				const { hasClassroom } = await import("../actions/config.ts");
				if (!hasClassroom(cfg)) {
					consola.error("GitHub Classroom not configured");
					process.exit(1);
				}

				const db = await requireDb(cfg);
				const { buildRepoMap } = await import("../apis/github/classroom.ts");
				const { pullRepos, sanitizeStudentDir } = await import("../apis/github/fetch.ts");
				const { join } = await import("node:path");

				try {
					// Get assignments from DB
					let ghAssignments = await db.selectFrom("gh_assignments").selectAll().execute();

					if (opts.assignment) {
						ghAssignments = ghAssignments.filter((a) => a.slug === opts.assignment);
						if (ghAssignments.length === 0) {
							consola.error(`Assignment not found: ${opts.assignment}`);
							process.exit(1);
						}
					}
					if (opts.limitAssignments && opts.limitAssignments > 0) {
						ghAssignments = ghAssignments.slice(0, opts.limitAssignments);
					}

					// Get student directory mappings
					const students = await db.selectFrom("students").selectAll().execute();
					const studentDirs = new Map<string, string>();
					for (const s of students) {
						if (s.github_username) {
							studentDirs.set(
								s.github_username,
								sanitizeStudentDir(s.sortable_name, s.github_username),
							);
						}
					}

					const baseDir = join(cfg.root, "repos");

					for (const assignment of ghAssignments) {
						consola.info(`Pulling repos for ${assignment.slug}...`);
						const repoMap = await buildRepoMap(assignment.gh_id);

						const counts = await pullRepos(repoMap, studentDirs, assignment.slug, baseDir, {
							limitStudents: opts.limitStudents || undefined,
						});

						consola.success(
							`${assignment.slug}: ${counts.cloned} cloned, ${counts.updated} updated, ${counts.upToDate} up-to-date, ${counts.errors} errors`,
						);
					}
				} finally {
					await db.destroy();
				}
			},
		);

	// ── delete ──
	cli
		.command("delete", "Delete the local database")
		.option("--yes, -y", "Skip confirmation")
		.action(async (opts: { yes?: boolean }) => {
			const cfg = await requireConfig();
			const { join } = await import("node:path");
			const { unlink } = await import("node:fs/promises");
			const dbFile = join(cfg.root, "cass.db");

			if (!(await Bun.file(dbFile).exists())) {
				consola.info("No database to delete");
				return;
			}

			if (!opts.yes) {
				const prompts = await import("@clack/prompts");
				const confirm = await prompts.confirm({ message: `Delete ${dbFile}?` });
				if (prompts.isCancel(confirm) || !confirm) {
					consola.info("Cancelled");
					return;
				}
			}

			// Also delete WAL/SHM files
			for (const suffix of ["", "-wal", "-shm"]) {
				try {
					await unlink(`${dbFile}${suffix}`);
				} catch {
					// File may not exist
				}
			}
			consola.success("Database deleted");
		});

	// ── backup ──
	cli
		.command("backup", "Backup the database")
		.option("-t, --tag <tag>", "Tag appended to filename")
		.option("-l, --list", "List existing backups")
		.action(async (opts: { tag?: string; list?: boolean }) => {
			const cfg = await requireConfig();
			const { join } = await import("node:path");
			const { mkdir, readdir } = await import("node:fs/promises");
			const backupDir = join(cfg.root, "backups");

			if (opts.list) {
				try {
					const files = await readdir(backupDir);
					const dbFiles = files.filter((f) => f.startsWith("cass_") && f.endsWith(".db"));
					if (dbFiles.length === 0) {
						consola.info("No backups found");
						return;
					}
					for (const f of dbFiles.sort().reverse()) {
						console.log(f);
					}
				} catch {
					consola.info("No backups found");
				}
				return;
			}

			const dbFile = join(cfg.root, "cass.db");
			if (!(await Bun.file(dbFile).exists())) {
				consola.error("No database to backup");
				process.exit(1);
			}

			await mkdir(backupDir, { recursive: true });

			// Ensure backups/ is in .gitignore
			const gitignorePath = join(cfg.root, ".gitignore");
			const gitignoreFile = Bun.file(gitignorePath);
			if (await gitignoreFile.exists()) {
				const content = await gitignoreFile.text();
				if (!content.includes("backups/")) {
					await Bun.write(gitignorePath, `${content.trimEnd()}\nbackups/\n`);
				}
			}

			const now = new Date();
			const ts = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
			const tag = opts.tag ? `_${opts.tag}` : "";
			const backupFile = join(backupDir, `cass_${ts}${tag}.db`);

			await Bun.write(backupFile, Bun.file(dbFile));
			consola.success(`Backup saved: ${backupFile}`);
		});

	// ── restore ──
	cli
		.command("restore <file>", "Restore database from backup")
		.option("--yes, -y", "Skip confirmation")
		.action(async (file: string, opts: { yes?: boolean }) => {
			const cfg = await requireConfig();
			const { join } = await import("node:path");
			const { resolve } = await import("node:path");

			const backupPath = resolve(file);
			if (!(await Bun.file(backupPath).exists())) {
				consola.error(`Backup file not found: ${backupPath}`);
				process.exit(1);
			}

			if (!opts.yes) {
				const prompts = await import("@clack/prompts");
				const confirm = await prompts.confirm({ message: `Restore from ${backupPath}?` });
				if (prompts.isCancel(confirm) || !confirm) {
					consola.info("Cancelled");
					return;
				}
			}

			const dbFile = join(cfg.root, "cass.db");

			// Delete existing WAL/SHM files
			const { unlink } = await import("node:fs/promises");
			for (const suffix of ["-wal", "-shm"]) {
				try {
					await unlink(`${dbFile}${suffix}`);
				} catch {
					// File may not exist
				}
			}

			await Bun.write(dbFile, Bun.file(backupPath));
			consola.success(`Restored from ${backupPath}`);
		});
}
