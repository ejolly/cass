/**
 * Canvas CLI commands — canvas, canvas-people, canvas-modules, canvas-assignments, etc.
 * All use flat cac command style (not nested subcommands).
 */
import type { CAC } from "cac";
import consola from "consola";

import type { Config } from "../actions/config.ts";
import { type OutputFormat, formatRows, formatTable } from "./report.ts";

// ─── Shared helpers ──────────────────────────────────────────────────

async function requireConfigWithCanvas(): Promise<Config> {
  const { getConfig, hasCanvas } = await import("../actions/config.ts");
  const cfg = await getConfig();
  if (!hasCanvas(cfg)) {
    consola.error("Canvas not configured in cass.toml");
    process.exit(1);
  }
  return cfg;
}

async function getCanvasClient(cfg: Config) {
  const { loadCanvasToken, createCanvasClient } = await import("../apis/canvas/client.ts");
  const token = await loadCanvasToken(cfg.root);
  return createCanvasClient({ baseUrl: cfg.canvasBaseUrl, token });
}

function outputFormat(opts: { csv?: boolean; save?: string }): OutputFormat {
  if (opts.csv) return "csv";
  if (opts.save) return "markdown";
  return "table";
}

async function outputRows(
  rows: Record<string, unknown>[],
  opts: { csv?: boolean; save?: string },
  title?: string,
) {
  const format = outputFormat(opts);
  const output = formatRows(rows, { format, title });
  if (opts.save) {
    await Bun.write(opts.save, `# ${title ?? "data"}\n\n${output}\n`);
    consola.success(`Saved to ${opts.save}`);
  } else {
    console.log(output);
  }
}

// ─── Registration ────────────────────────────────────────────────────

export function registerCanvasCommands(cli: CAC): void {
  // ── canvas (course overview) ──
  cli.command("canvas", "Canvas course overview").action(async () => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const { getPaginated } = await import("../apis/canvas/client.ts");

    const [course] = await getPaginated<{
      id: number;
      name: string;
      course_code: string;
      workflow_state: string;
    }>(client, `courses/${cfg.canvasCourseId}`);

    consola.box(`${course?.name ?? "Course"} (${cfg.canvasCourseId})`);
    if (course) {
      consola.info(`Code: ${course.course_code}`);
      consola.info(`State: ${course.workflow_state}`);
    }
  });

  // ── canvas-people ──
  cli
    .command("canvas-people", "List Canvas course users")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const users = await getPaginated<{
        id: number;
        name: string;
        sortable_name: string;
        email?: string;
        sis_user_id?: string;
        enrollments?: Array<{ role: string }>;
      }>(client, `courses/${cfg.canvasCourseId}/users`, { include: "enrollments" });

      const rows = users.map((u) => ({
        ID: u.id,
        Name: u.name,
        Role: u.enrollments?.[0]?.role ?? "",
        Email: u.email ?? "",
        "SIS ID": u.sis_user_id ?? "",
      }));

      await outputRows(rows, opts, "People");
    });

  // ── canvas-modules ──
  cli
    .command("canvas-modules", "List Canvas modules")
    .option("--id <id>", "Show items for a specific module")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { id?: string; csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated, resolveResource } = await import("../apis/canvas/client.ts");

      if (opts.id) {
        const modules = await getPaginated<{ id: number; name: string }>(
          client,
          `courses/${cfg.canvasCourseId}/modules`,
        );
        const mod = await resolveResource(modules, opts.id);
        const items = await getPaginated<{
          id: number;
          title: string;
          type: string;
          position: number;
          content_id?: number;
          url?: string;
        }>(client, `courses/${cfg.canvasCourseId}/modules/${mod.id}/items`);

        const rows = items.map((i) => ({
          ID: i.id,
          Position: i.position,
          Title: i.title,
          Type: i.type,
        }));
        await outputRows(rows, opts, `Module: ${mod.name}`);
      } else {
        const modules = await getPaginated<{
          id: number;
          name: string;
          position: number;
          published: boolean;
          items_count: number;
        }>(client, `courses/${cfg.canvasCourseId}/modules`);

        const rows = modules.map((m) => ({
          ID: m.id,
          Position: m.position,
          Name: m.name,
          Published: m.published ? "yes" : "no",
          Items: m.items_count,
        }));
        await outputRows(rows, opts, "Modules");
      }
    });

  // ── canvas-modules-create ──
  cli
    .command("canvas-modules-create <name>", "Create a Canvas module")
    .option("--position <n>", "Position")
    .action(async (name: string, opts: { position?: number }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);

      const body: Record<string, unknown> = { module: { name } };
      if (opts.position) (body.module as Record<string, unknown>).position = opts.position;

      const result = await client
        .post(`courses/${cfg.canvasCourseId}/modules`, { json: body })
        .json<{ id: number; name: string }>();
      consola.success(`Created module: ${result.name} (id=${result.id})`);
    });

  // ── canvas-modules-publish / unpublish / delete ──
  registerModuleAction(
    cli,
    "canvas-modules-publish",
    "Publish a Canvas module",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/modules/${id}`, {
          json: { module: { published: true } },
        })
        .json();
      consola.success(`Published module ${id}`);
    },
  );

  registerModuleAction(
    cli,
    "canvas-modules-unpublish",
    "Unpublish a Canvas module",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/modules/${id}`, {
          json: { module: { published: false } },
        })
        .json();
      consola.success(`Unpublished module ${id}`);
    },
  );

  cli
    .command("canvas-modules-delete <id>", "Delete a Canvas module")
    .option("--yes, -y", "Skip confirmation")
    .action(async (idOrName: string, opts: { yes?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const id = await resolveModuleId(client, cfg, idOrName);

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Delete module ${id}?` });
        if (prompts.isCancel(confirm) || !confirm) return;
      }

      await client.delete(`courses/${cfg.canvasCourseId}/modules/${id}`).json();
      consola.success(`Deleted module ${id}`);
    });

  // ── canvas-modules-add-item ──
  cli
    .command("canvas-modules-add-item <id>", "Add item to a Canvas module")
    .option("--type <type>", "Item type (e.g. Assignment, Quiz, File)")
    .option("--content-id <id>", "Canvas content ID")
    .option("--title <title>", "Item title")
    .action(async (idOrName: string, opts: { type: string; contentId: number; title?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const modId = await resolveModuleId(client, cfg, idOrName);

      const item: Record<string, unknown> = {
        type: opts.type,
        content_id: opts.contentId,
      };
      if (opts.title) item.title = opts.title;

      const result = await client
        .post(`courses/${cfg.canvasCourseId}/modules/${modId}/items`, {
          json: { module_item: item },
        })
        .json<{ id: number; title: string }>();
      consola.success(`Added item: ${result.title} (id=${result.id})`);
    });

  // ── canvas-assignments ──
  cli
    .command("canvas-assignments", "List Canvas assignments")
    .option("--id <id>", "Show details for a specific assignment")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { id?: string; csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated, resolveResource } = await import("../apis/canvas/client.ts");

      const assignments = await getPaginated<{
        id: number;
        name: string;
        points_possible: number;
        due_at: string | null;
        published: boolean;
        assignment_group_id: number;
      }>(client, `courses/${cfg.canvasCourseId}/assignments`);

      if (opts.id) {
        const a = await resolveResource(assignments, opts.id);
        console.log(
          formatTable(
            [
              {
                ID: a.id,
                Name: a.name,
                Points: a.points_possible,
                Due: a.due_at ?? "",
                Published: a.published ? "yes" : "no",
              },
            ],
            { title: a.name },
          ),
        );
      } else {
        const rows = assignments.map((a) => ({
          ID: a.id,
          Name: a.name,
          Points: a.points_possible,
          Due: a.due_at ?? "",
          Published: a.published ? "yes" : "no",
        }));
        await outputRows(rows, opts, "Assignments");
      }
    });

  // ── canvas-assignments-groups ──
  cli
    .command("canvas-assignments-groups", "List Canvas assignment groups")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const groups = await getPaginated<{
        id: number;
        name: string;
        group_weight: number;
        position: number;
      }>(client, `courses/${cfg.canvasCourseId}/assignment_groups`);

      const rows = groups.map((g) => ({
        ID: g.id,
        Name: g.name,
        Weight: g.group_weight,
        Position: g.position,
      }));
      await outputRows(rows, opts, "Assignment Groups");
    });

  // ── canvas-assignments-create ──
  cli
    .command("canvas-assignments-create <name>", "Create a Canvas assignment")
    .option("--group <name>", "Assignment group name")
    .option("--points <n>", "Points possible", { default: 0 })
    .option("--due <date>", "Due date (ISO 8601)")
    .option("--type <type>", "Submission type", { default: "online_url" })
    .option("--publish", "Publish immediately")
    .action(
      async (
        name: string,
        opts: { group: string; points: number; due?: string; type: string; publish?: boolean },
      ) => {
        const cfg = await requireConfigWithCanvas();
        const client = await getCanvasClient(cfg);
        const { getPaginated } = await import("../apis/canvas/client.ts");

        // Resolve assignment group
        const groups = await getPaginated<{ id: number; name: string }>(
          client,
          `courses/${cfg.canvasCourseId}/assignment_groups`,
        );
        const group = groups.find((g) => g.name.toLowerCase() === opts.group.toLowerCase());
        if (!group) {
          consola.error(`Assignment group not found: ${opts.group}`);
          process.exit(1);
        }

        const assignment: Record<string, unknown> = {
          name,
          assignment_group_id: group.id,
          points_possible: opts.points,
          submission_types: [opts.type],
          published: opts.publish ?? false,
        };
        if (opts.due) assignment.due_at = opts.due;

        const result = await client
          .post(`courses/${cfg.canvasCourseId}/assignments`, { json: { assignment } })
          .json<{ id: number; name: string }>();
        consola.success(`Created assignment: ${result.name} (id=${result.id})`);
      },
    );

  // ── canvas-assignments-publish / unpublish / delete ──
  registerAssignmentAction(
    cli,
    "canvas-assignments-publish",
    "Publish a Canvas assignment",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/assignments/${id}`, {
          json: { assignment: { published: true } },
        })
        .json();
      consola.success(`Published assignment ${id}`);
    },
  );

  registerAssignmentAction(
    cli,
    "canvas-assignments-unpublish",
    "Unpublish a Canvas assignment",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/assignments/${id}`, {
          json: { assignment: { published: false } },
        })
        .json();
      consola.success(`Unpublished assignment ${id}`);
    },
  );

  cli
    .command("canvas-assignments-delete <id>", "Delete a Canvas assignment")
    .option("--yes, -y", "Skip confirmation")
    .action(async (idOrName: string, opts: { yes?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const id = await resolveAssignmentId(client, cfg, idOrName);

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Delete assignment ${id}?` });
        if (prompts.isCancel(confirm) || !confirm) return;
      }

      await client.delete(`courses/${cfg.canvasCourseId}/assignments/${id}`).json();
      consola.success(`Deleted assignment ${id}`);
    });

  // ── canvas-quizzes ──
  cli
    .command("canvas-quizzes", "List Canvas quizzes")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const quizzes = await getPaginated<{
        id: number;
        title: string;
        quiz_type: string;
        question_count: number;
        points_possible: number | null;
        published: boolean;
      }>(client, `courses/${cfg.canvasCourseId}/quizzes`);

      const rows = quizzes.map((q) => ({
        ID: q.id,
        Title: q.title,
        Type: q.quiz_type,
        Questions: q.question_count,
        Points: q.points_possible ?? "",
        Published: q.published ? "yes" : "no",
      }));
      await outputRows(rows, opts, "Quizzes");
    });

  // ── canvas-quizzes-create ──
  cli
    .command("canvas-quizzes-create <title>", "Create a Canvas quiz")
    .option("--type <type>", "Quiz type", { default: "assignment" })
    .option("--points <n>", "Points possible")
    .option("--publish", "Publish immediately")
    .option("--time-limit <min>", "Time limit in minutes")
    .action(
      async (
        title: string,
        opts: { type: string; points?: number; publish?: boolean; timeLimit?: number },
      ) => {
        const cfg = await requireConfigWithCanvas();
        const client = await getCanvasClient(cfg);

        const quiz: Record<string, unknown> = {
          title,
          quiz_type: opts.type,
          published: opts.publish ?? false,
        };
        if (opts.points !== undefined) quiz.points_possible = opts.points;
        if (opts.timeLimit !== undefined) quiz.time_limit = opts.timeLimit;

        const result = await client
          .post(`courses/${cfg.canvasCourseId}/quizzes`, { json: { quiz } })
          .json<{ id: number; title: string }>();
        consola.success(`Created quiz: ${result.title} (id=${result.id})`);
      },
    );

  // ── canvas-quizzes publish / unpublish / delete ──
  registerQuizAction(
    cli,
    "canvas-quizzes-publish",
    "Publish a Canvas quiz",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/quizzes/${id}`, { json: { quiz: { published: true } } })
        .json();
      consola.success(`Published quiz ${id}`);
    },
  );

  registerQuizAction(
    cli,
    "canvas-quizzes-unpublish",
    "Unpublish a Canvas quiz",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/quizzes/${id}`, {
          json: { quiz: { published: false } },
        })
        .json();
      consola.success(`Unpublished quiz ${id}`);
    },
  );

  cli
    .command("canvas-quizzes-delete <id>", "Delete a Canvas quiz")
    .option("--yes, -y", "Skip confirmation")
    .action(async (idOrName: string, opts: { yes?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Delete quiz ${idOrName}?` });
        if (prompts.isCancel(confirm) || !confirm) return;
      }

      await client.delete(`courses/${cfg.canvasCourseId}/quizzes/${idOrName}`).json();
      consola.success(`Deleted quiz ${idOrName}`);
    });

  // ── canvas-files ──
  cli
    .command("canvas-files", "List Canvas course files")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const files = await getPaginated<{
        id: number;
        display_name: string;
        size: number;
        "content-type": string;
        folder_id: number;
        created_at: string;
      }>(client, `courses/${cfg.canvasCourseId}/files`);

      const rows = files.map((f) => ({
        ID: f.id,
        Name: f.display_name,
        Size: f.size,
        Type: f["content-type"],
        Created: f.created_at,
      }));
      await outputRows(rows, opts, "Files");
    });

  // ── canvas-files-upload ──
  cli
    .command("canvas-files-upload <path>", "Upload a file to Canvas")
    .option("--folder <name>", "Destination folder")
    .action(async (filePath: string, opts: { folder?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { basename } = await import("node:path");

      const file = Bun.file(filePath);
      if (!(await file.exists())) {
        consola.error(`File not found: ${filePath}`);
        process.exit(1);
      }

      const name = basename(filePath);
      const size = file.size;

      // Step 1: Notify Canvas
      const params: Record<string, unknown> = { name, size };
      if (opts.folder) params.parent_folder_path = opts.folder;

      const notify = await client
        .post(`courses/${cfg.canvasCourseId}/files`, { json: params })
        .json<{ upload_url: string; upload_params: Record<string, string> }>();

      // Step 2: Upload file
      const formData = new FormData();
      for (const [k, v] of Object.entries(notify.upload_params)) {
        formData.append(k, v);
      }
      formData.append("file", file);

      await fetch(notify.upload_url, { method: "POST", body: formData });
      consola.success(`Uploaded: ${name}`);
    });

  // ── canvas-files-delete ──
  cli
    .command("canvas-files-delete <id>", "Delete a Canvas file")
    .option("--yes, -y", "Skip confirmation")
    .action(async (fileId: string, opts: { yes?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Delete file ${fileId}?` });
        if (prompts.isCancel(confirm) || !confirm) return;
      }

      await client.delete(`files/${fileId}`).json();
      consola.success(`Deleted file ${fileId}`);
    });

  // ── canvas-announcements ──
  cli
    .command("canvas-announcements", "List Canvas announcements")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const announcements = await getPaginated<{
        id: number;
        title: string;
        posted_at: string;
        author: { display_name: string };
      }>(client, `courses/${cfg.canvasCourseId}/discussion_topics`, { only_announcements: "true" });

      const rows = announcements.map((a) => ({
        ID: a.id,
        Title: a.title,
        Posted: a.posted_at,
        Author: a.author?.display_name ?? "",
      }));
      await outputRows(rows, opts, "Announcements");
    });

  // ── canvas-announcements-create ──
  cli
    .command("canvas-announcements-create <title>", "Create a Canvas announcement")
    .option("-m, --message <html>", "HTML message body")
    .action(async (title: string, opts: { message: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);

      const result = await client
        .post(`courses/${cfg.canvasCourseId}/discussion_topics`, {
          json: { title, message: opts.message, is_announcement: true },
        })
        .json<{ id: number; title: string }>();
      consola.success(`Created announcement: ${result.title} (id=${result.id})`);
    });

  // ── canvas-announcements-update ──
  cli
    .command("canvas-announcements-update <id>", "Update a Canvas announcement")
    .option("--title <title>", "New title")
    .option("-m, --message <html>", "New HTML message")
    .action(async (topicId: string, opts: { title?: string; message?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);

      const body: Record<string, unknown> = {};
      if (opts.title) body.title = opts.title;
      if (opts.message) body.message = opts.message;

      await client
        .put(`courses/${cfg.canvasCourseId}/discussion_topics/${topicId}`, { json: body })
        .json();
      consola.success(`Updated announcement ${topicId}`);
    });

  // ── canvas-announcements-delete ──
  cli
    .command("canvas-announcements-delete <id>", "Delete a Canvas announcement")
    .option("--yes, -y", "Skip confirmation")
    .action(async (topicId: string, opts: { yes?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);

      if (!opts.yes) {
        const prompts = await import("@clack/prompts");
        const confirm = await prompts.confirm({ message: `Delete announcement ${topicId}?` });
        if (prompts.isCancel(confirm) || !confirm) return;
      }

      await client.delete(`courses/${cfg.canvasCourseId}/discussion_topics/${topicId}`).json();
      consola.success(`Deleted announcement ${topicId}`);
    });

  // ── canvas-tabs ──
  cli
    .command("canvas-tabs", "List Canvas navigation tabs")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const tabs = await getPaginated<{
        id: string;
        label: string;
        type: string;
        position: number;
        visibility: string;
      }>(client, `courses/${cfg.canvasCourseId}/tabs`);

      const rows = tabs.map((t) => ({
        ID: t.id,
        Label: t.label,
        Type: t.type,
        Position: t.position,
        Visibility: t.visibility,
      }));
      await outputRows(rows, opts, "Tabs");
    });

  // ── canvas-tabs-show / hide ──
  cli
    .command("canvas-tabs-show <id>", "Show a Canvas navigation tab")
    .action(async (tabId: string) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      await client
        .put(`courses/${cfg.canvasCourseId}/tabs/${tabId}`, { json: { hidden: false } })
        .json();
      consola.success(`Tab ${tabId} is now visible`);
    });

  cli
    .command("canvas-tabs-hide <id>", "Hide a Canvas navigation tab")
    .action(async (tabId: string) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      await client
        .put(`courses/${cfg.canvasCourseId}/tabs/${tabId}`, { json: { hidden: true } })
        .json();
      consola.success(`Tab ${tabId} is now hidden`);
    });

  // ── canvas-sync ──
  cli
    .command("canvas-sync", "Sync modules and assignments from cass.toml to Canvas")
    .option("--push", "Apply changes (default is dry-run)")
    .option("--force", "Force overwrite existing resources")
    .action(async (opts: { push?: boolean; force?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("../apis/canvas/client.ts");

      const dryRun = !opts.push;
      if (dryRun) consola.info("Dry run mode (use --push to apply)");

      // Sync modules
      if (cfg.canvasModules.length > 0) {
        const existing = await getPaginated<{ id: number; name: string; published: boolean }>(
          client,
          `courses/${cfg.canvasCourseId}/modules`,
        );
        for (const spec of cfg.canvasModules) {
          const found = existing.find((m) => m.name.toLowerCase() === spec.name.toLowerCase());
          if (found) {
            if (spec.published !== found.published) {
              consola.info(`Module "${spec.name}": update published=${spec.published}`);
              if (!dryRun) {
                await client
                  .put(`courses/${cfg.canvasCourseId}/modules/${found.id}`, {
                    json: { module: { published: spec.published } },
                  })
                  .json();
              }
            } else {
              consola.info(`Module "${spec.name}": up to date`);
            }
          } else {
            consola.info(`Module "${spec.name}": create`);
            if (!dryRun) {
              await client
                .post(`courses/${cfg.canvasCourseId}/modules`, {
                  json: { module: { name: spec.name, published: spec.published } },
                })
                .json();
            }
          }
        }
      }

      // Sync assignments
      if (cfg.canvasAssignments.length > 0) {
        const existing = await getPaginated<{ id: number; name: string }>(
          client,
          `courses/${cfg.canvasCourseId}/assignments`,
        );

        for (const spec of cfg.canvasAssignments) {
          const found = existing.find((a) => a.name.toLowerCase() === spec.name.toLowerCase());
          if (found) {
            if (opts.force) {
              consola.info(`Assignment "${spec.name}": update (force)`);
              if (!dryRun) {
                await client
                  .put(`courses/${cfg.canvasCourseId}/assignments/${found.id}`, {
                    json: {
                      assignment: {
                        points_possible: spec.points,
                        submission_types: spec.submission_types,
                        due_at: spec.due_at || undefined,
                        published: spec.published,
                      },
                    },
                  })
                  .json();
              }
            } else {
              consola.info(`Assignment "${spec.name}": exists (skip)`);
            }
          } else {
            consola.info(`Assignment "${spec.name}": create`);
            if (!dryRun) {
              // Resolve group
              const groups = await getPaginated<{ id: number; name: string }>(
                client,
                `courses/${cfg.canvasCourseId}/assignment_groups`,
              );
              const group = groups.find((g) => g.name.toLowerCase() === spec.group.toLowerCase());

              await client
                .post(`courses/${cfg.canvasCourseId}/assignments`, {
                  json: {
                    assignment: {
                      name: spec.name,
                      points_possible: spec.points,
                      submission_types: spec.submission_types,
                      due_at: spec.due_at || undefined,
                      published: spec.published,
                      assignment_group_id: group?.id,
                    },
                  },
                })
                .json();
            }
          }
        }
      }

      consola.success(dryRun ? "Dry run complete" : "Sync complete");
    });
}

// ─── Resolution helpers ──────────────────────────────────────────────

async function resolveModuleId(
  client: import("ky").KyInstance,
  cfg: Config,
  idOrName: string,
): Promise<number> {
  const numId = Number(idOrName);
  if (!Number.isNaN(numId) && String(numId) === idOrName) return numId;

  const { getPaginated, resolveResource } = await import("../apis/canvas/client.ts");
  const modules = await getPaginated<{ id: number; name: string }>(
    client,
    `courses/${cfg.canvasCourseId}/modules`,
  );
  const mod = await resolveResource(modules, idOrName);
  return mod.id;
}

async function resolveAssignmentId(
  client: import("ky").KyInstance,
  cfg: Config,
  idOrName: string,
): Promise<number> {
  const numId = Number(idOrName);
  if (!Number.isNaN(numId) && String(numId) === idOrName) return numId;

  const { getPaginated, resolveResource } = await import("../apis/canvas/client.ts");
  const assignments = await getPaginated<{ id: number; name: string }>(
    client,
    `courses/${cfg.canvasCourseId}/assignments`,
  );
  const a = await resolveResource(assignments, idOrName);
  return a.id;
}

// ─── DRY helpers for publish/unpublish patterns ──────────────────────

function registerModuleAction(
  cli: CAC,
  name: string,
  desc: string,
  action: (client: import("ky").KyInstance, cfg: Config, id: number) => Promise<void>,
) {
  cli.command(`${name} <id>`, desc).action(async (idOrName: string) => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const id = await resolveModuleId(client, cfg, idOrName);
    await action(client, cfg, id);
  });
}

function registerAssignmentAction(
  cli: CAC,
  name: string,
  desc: string,
  action: (client: import("ky").KyInstance, cfg: Config, id: number) => Promise<void>,
) {
  cli.command(`${name} <id>`, desc).action(async (idOrName: string) => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const id = await resolveAssignmentId(client, cfg, idOrName);
    await action(client, cfg, id);
  });
}

function registerQuizAction(
  cli: CAC,
  name: string,
  desc: string,
  action: (client: import("ky").KyInstance, cfg: Config, id: number) => Promise<void>,
) {
  cli.command(`${name} <id>`, desc).action(async (idOrName: string) => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    // Quizzes use title, not name
    const numId = Number(idOrName);
    if (!Number.isNaN(numId) && String(numId) === idOrName) {
      await action(client, cfg, numId);
      return;
    }
    const { getPaginated } = await import("../apis/canvas/client.ts");
    const quizzes = await getPaginated<{ id: number; title: string }>(
      client,
      `courses/${cfg.canvasCourseId}/quizzes`,
    );
    const found = quizzes.find((q) => q.title.toLowerCase() === idOrName.toLowerCase());
    if (!found) throw new Error(`Quiz not found: ${idOrName}`);
    await action(client, cfg, found.id);
  });
}
