/**
 * CSV/Markdown export — writes filtered table data to files.
 */

function timestamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)
}

function escapeCsv(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

/** Export rows as CSV to cwd. Returns the written file path. */
export function exportCsv(
  rows: Record<string, unknown>[],
  columns: string[],
  tableName: string,
): string {
  const header = columns.map(escapeCsv).join(",")
  const body = rows.map((row) =>
    columns.map((col) => escapeCsv(String(row[col] ?? ""))).join(",")
  )
  const csv = [header, ...body].join("\n")
  const path = `${tableName}_${timestamp()}.csv`
  Bun.write(path, csv)
  return path
}

/** Export rows as Markdown table. Returns the written file path. */
export function exportMarkdown(
  rows: Record<string, unknown>[],
  columns: string[],
  tableName: string,
): string {
  const header = `| ${columns.join(" | ")} |`
  const separator = `| ${columns.map(() => "---").join(" | ")} |`
  const body = rows.map((row) =>
    `| ${columns.map((col) => String(row[col] ?? "")).join(" | ")} |`
  )
  const md = [header, separator, ...body].join("\n")
  const path = `${tableName}_${timestamp()}.md`
  Bun.write(path, md)
  return path
}
