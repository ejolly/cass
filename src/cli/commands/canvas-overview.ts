import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas — course overview + people.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli.command("canvas", "Canvas course overview").action(async () => {
    const cfg = await requireConfigWithCanvas();
    const client = await getCanvasClient(cfg);
    const { getPaginated } = await import("@/apis/canvas/client.ts");

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

  cli
    .command("canvas-people", "List Canvas course users")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

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
}
