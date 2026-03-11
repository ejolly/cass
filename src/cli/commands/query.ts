import { requireConfig, requireDb } from "@/cli/helpers.ts";
import { type OutputFormat, formatRows } from "@/cli/report.ts";
/**
 * query — query datasets (students, assignments, submissions, gradebook).
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("query [dataset]", "Query datasets (students, assignments, submissions, gradebook)")
    .option("--where <expr>", "Filter expression")
    .option("--order <expr>", "Order expression")
    .option("--limit <n>", "Limit rows", { default: 0 })
    .option("--sql <query>", "Raw SQL query")
    .option("--csv", "Output as CSV")
    .option("--save <path>", "Save as markdown file")
    .action(
      async (
        dataset: string | undefined,
        opts: {
          where?: string;
          order?: string;
          limit?: number;
          sql?: string;
          csv?: boolean;
          save?: string;
        },
      ) => {
        const cfg = await requireConfig();
        const db = await requireDb(cfg);

        try {
          let rows: Record<string, unknown>[];

          if (opts.sql) {
            const { rawQuery } = await import("@/db/introspection.ts");
            rows = await rawQuery(db, opts.sql);
          } else if (dataset) {
            const { queryDataset } = await import("@/db/queries.ts");
            const validDatasets = ["students", "assignments", "submissions", "gradebook"] as const;
            if (!validDatasets.includes(dataset as (typeof validDatasets)[number])) {
              consola.error(`Unknown dataset: ${dataset}. Use: ${validDatasets.join(", ")}`);
              process.exit(1);
            }
            rows = await queryDataset(db, dataset as (typeof validDatasets)[number], {
              where: opts.where,
              order: opts.order,
              limit: opts.limit || undefined,
            });
          } else {
            consola.error("Provide a dataset name or --sql query");
            process.exit(1);
          }

          const format: OutputFormat = opts.csv ? "csv" : opts.save ? "markdown" : "table";
          const output = formatRows(rows, { format, title: dataset });

          if (opts.save) {
            await Bun.write(opts.save, `# ${dataset ?? "query"}\n\n${output}\n`);
            consola.success(`Saved to ${opts.save}`);
          } else {
            console.log(output);
          }
        } finally {
          await db.destroy();
        }
      },
    );
}
