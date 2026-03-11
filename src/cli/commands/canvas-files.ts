import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas-files — list, upload, delete.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli
    .command("canvas-files", "List Canvas course files")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

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

      const params: Record<string, unknown> = { name, size };
      if (opts.folder) params.parent_folder_path = opts.folder;

      const notify = await client
        .post(`courses/${cfg.canvasCourseId}/files`, { json: params })
        .json<{ upload_url: string; upload_params: Record<string, string> }>();

      const formData = new FormData();
      for (const [k, v] of Object.entries(notify.upload_params)) {
        formData.append(k, v);
      }
      formData.append("file", file);

      await fetch(notify.upload_url, { method: "POST", body: formData });
      consola.success(`Uploaded: ${name}`);
    });

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
}
