import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas-announcements — list, create, update, delete.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli
    .command("canvas-announcements", "List Canvas announcements")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

      const announcements = await getPaginated<{
        id: number;
        title: string;
        posted_at: string;
        author: { display_name: string };
      }>(client, `courses/${cfg.canvasCourseId}/discussion_topics`, {
        only_announcements: "true",
      });

      const rows = announcements.map((a) => ({
        ID: a.id,
        Title: a.title,
        Posted: a.posted_at,
        Author: a.author?.display_name ?? "",
      }));
      await outputRows(rows, opts, "Announcements");
    });

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
}
