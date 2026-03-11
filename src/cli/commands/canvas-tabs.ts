import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas-tabs — list, show, hide.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli
    .command("canvas-tabs", "List Canvas navigation tabs")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

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
}
