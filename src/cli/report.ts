import { toCsv, toCsvWithColumns } from "@/utils/csv.ts";
/**
 * Shared table rendering — cli-table3 tables, CSV, and markdown export.
 */
import Table from "cli-table3";

export type OutputFormat = "table" | "csv" | "markdown";

export interface FormatTableOptions {
  title?: string;
  columns?: string[];
}

/** Render rows as a cli-table3 ASCII table string. */
export function formatTable(
  rows: Record<string, unknown>[],
  opts: FormatTableOptions = {},
): string {
  if (rows.length === 0) return "No data";

  const columns = opts.columns ?? Object.keys(rows[0]!);
  const table = new Table({ head: columns });

  for (const row of rows) {
    table.push(columns.map((col) => String(row[col] ?? "")));
  }

  const rendered = table.toString();
  const count = `${rows.length} row${rows.length === 1 ? "" : "s"}`;

  if (opts.title) {
    return `${opts.title}\n${rendered}\n${count}`;
  }
  return `${rendered}\n${count}`;
}

/** Render rows as CSV string. */
export function formatCsv(rows: Record<string, unknown>[], columns?: string[]): string {
  if (rows.length === 0) return "";
  if (columns) return toCsvWithColumns(rows, columns);
  return toCsv(rows);
}

/** Render rows as a GFM markdown table. */
export function formatMarkdown(rows: Record<string, unknown>[], columns?: string[]): string {
  if (rows.length === 0) return "";

  const cols = columns ?? Object.keys(rows[0]!);
  const lines: string[] = [];

  lines.push(`| ${cols.join(" | ")} |`);
  lines.push(`| ${cols.map(() => "---").join(" | ")} |`);

  for (const row of rows) {
    lines.push(`| ${cols.map((c) => String(row[c] ?? "")).join(" | ")} |`);
  }

  return lines.join("\n");
}

export interface FormatRowsOptions {
  format: OutputFormat;
  title?: string;
  columns?: string[];
}

/** Dispatch to the appropriate formatter. */
export function formatRows(rows: Record<string, unknown>[], opts: FormatRowsOptions): string {
  switch (opts.format) {
    case "csv":
      return formatCsv(rows, opts.columns);
    case "markdown":
      return formatMarkdown(rows, opts.columns);
    case "table":
      return formatTable(rows, { title: opts.title, columns: opts.columns });
  }
}
