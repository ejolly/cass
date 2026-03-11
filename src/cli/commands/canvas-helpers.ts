import type { Config } from "@/actions/config.ts";
import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
import { type OutputFormat, formatRows } from "@/cli/report.ts";
/**
 * Canvas CLI shared helpers — resolution, output, and DRY registration patterns.
 */
import type { CAC } from "cac";
import type { KyInstance } from "ky";

export function outputFormat(opts: { csv?: boolean; save?: string }): OutputFormat {
  if (opts.csv) return "csv";
  if (opts.save) return "markdown";
  return "table";
}

export async function outputRows(
  rows: Record<string, unknown>[],
  opts: { csv?: boolean; save?: string },
  title?: string,
) {
  const format = outputFormat(opts);
  const output = formatRows(rows, { format, title });
  if (opts.save) {
    await Bun.write(opts.save, `# ${title ?? "data"}\n\n${output}\n`);
    const consola = (await import("consola")).default;
    consola.success(`Saved to ${opts.save}`);
  } else {
    console.log(output);
  }
}

export async function resolveModuleId(
  client: KyInstance,
  cfg: Config,
  idOrName: string,
): Promise<number> {
  const numId = Number(idOrName);
  if (!Number.isNaN(numId) && String(numId) === idOrName) return numId;

  const { getPaginated, resolveResource } = await import("@/apis/canvas/client.ts");
  const modules = await getPaginated<{ id: number; name: string }>(
    client,
    `courses/${cfg.canvasCourseId}/modules`,
  );
  const mod = await resolveResource(modules, idOrName);
  return mod.id;
}

export async function resolveAssignmentId(
  client: KyInstance,
  cfg: Config,
  idOrName: string,
): Promise<number> {
  const numId = Number(idOrName);
  if (!Number.isNaN(numId) && String(numId) === idOrName) return numId;

  const { getPaginated, resolveResource } = await import("@/apis/canvas/client.ts");
  const assignments = await getPaginated<{ id: number; name: string }>(
    client,
    `courses/${cfg.canvasCourseId}/assignments`,
  );
  const a = await resolveResource(assignments, idOrName);
  return a.id;
}

export function registerModuleAction(
  cli: CAC,
  name: string,
  desc: string,
  action: (client: KyInstance, cfg: Config, id: number) => Promise<void>,
) {
  cli.command(`${name} <id>`, desc).action(async (idOrName: string) => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const id = await resolveModuleId(client, cfg, idOrName);
    await action(client, cfg, id);
  });
}

export function registerAssignmentAction(
  cli: CAC,
  name: string,
  desc: string,
  action: (client: KyInstance, cfg: Config, id: number) => Promise<void>,
) {
  cli.command(`${name} <id>`, desc).action(async (idOrName: string) => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const id = await resolveAssignmentId(client, cfg, idOrName);
    await action(client, cfg, id);
  });
}

export function registerQuizAction(
  cli: CAC,
  name: string,
  desc: string,
  action: (client: KyInstance, cfg: Config, id: number) => Promise<void>,
) {
  cli.command(`${name} <id>`, desc).action(async (idOrName: string) => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const numId = Number(idOrName);
    if (!Number.isNaN(numId) && String(numId) === idOrName) {
      await action(client, cfg, numId);
      return;
    }
    const { getPaginated } = await import("@/apis/canvas/client.ts");
    const quizzes = await getPaginated<{ id: number; title: string }>(
      client,
      `courses/${cfg.canvasCourseId}/quizzes`,
    );
    const found = quizzes.find((q) => q.title.toLowerCase() === idOrName.toLowerCase());
    if (!found) throw new Error(`Quiz not found: ${idOrName}`);
    await action(client, cfg, found.id);
  });
}
