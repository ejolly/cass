import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas-modules — list, create, publish, unpublish, delete, add-item.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows, registerModuleAction, resolveModuleId } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli
    .command("canvas-modules", "List Canvas modules")
    .option("--id <id>", "Show items for a specific module")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { id?: string; csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated, resolveResource } = await import("@/apis/canvas/client.ts");

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
}
