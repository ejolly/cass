import { getCanvasClient, requireConfigWithCanvas } from "@/cli/helpers.ts";
/**
 * canvas-quizzes — list, create, publish, unpublish, delete.
 */
import type { CAC } from "cac";
import consola from "consola";
import { outputRows, registerQuizAction } from "./canvas-helpers.ts";

export function register(cli: CAC): void {
  cli
    .command("canvas-quizzes", "List Canvas quizzes")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown")
    .action(async (opts: { csv?: boolean; save?: string }) => {
      const cfg = await requireConfigWithCanvas();
      const client = await getCanvasClient(cfg);
      const { getPaginated } = await import("@/apis/canvas/client.ts");

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

  registerQuizAction(
    cli,
    "canvas-quizzes-publish",
    "Publish a Canvas quiz",
    async (client, cfg, id) => {
      await client
        .put(`courses/${cfg.canvasCourseId}/quizzes/${id}`, {
          json: { quiz: { published: true } },
        })
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
}
