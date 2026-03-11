import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas-sync — sync modules and assignments from cass.toml to Canvas.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("canvas-sync", "Sync modules and assignments from cass.toml to Canvas")
    .option("--push", "Apply changes (default is dry-run)")
    .option("--force", "Force overwrite existing resources")
    .action(async (opts: { push?: boolean; force?: boolean }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

      const dryRun = !opts.push;
      if (dryRun) consola.info("Dry run mode (use --push to apply)");

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
