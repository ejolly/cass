import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
import { formatTable } from "@/cli/report.ts";
/**
 * canvas-assignments — list, create, publish, unpublish, delete, groups.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows, registerAssignmentAction, resolveAssignmentId } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli
    .command("canvas-assignments", "List Canvas assignments")
    .option("--id <id>", "Show details for a specific assignment")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { id?: string; csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated, resolveResource } = await import("@/apis/canvas/client.ts");

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

  cli
    .command("canvas-assignments-groups", "List Canvas assignment groups")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

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
        const { getPaginated } = await import("@/apis/canvas/client.ts");

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
}
