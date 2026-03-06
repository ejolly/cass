import type {
  TableInfo,
  TableSchema,
  TableData,
  Row,
  UpdateResult,
  PendingSummary,
  PreviewData,
  PushResult,
} from "./types.js";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Fetch list of all tables. */
export async function fetchTables(): Promise<TableInfo[]> {
  const data = await fetchJson<{ tables: TableInfo[] }>("/api/tables");
  return data.tables;
}

/** Fetch schema for a table. */
export async function fetchSchema(table: string): Promise<TableSchema> {
  return fetchJson<TableSchema>(`/api/schema/${table}`);
}

/** Fetch all rows from a table. */
export async function fetchTableData(table: string): Promise<TableData> {
  return fetchJson<TableData>(`/api/table/${table}`);
}

/** Fetch schema and data in parallel. */
export async function fetchSchemaAndData(
  table: string,
): Promise<{ schema: TableSchema; data: TableData }> {
  const [schema, data] = await Promise.all([
    fetchSchema(table),
    fetchTableData(table),
  ]);
  return { schema, data };
}

/** Fetch pending Canvas changes count. */
export async function fetchPending(): Promise<PendingSummary> {
  return fetchJson<PendingSummary>("/api/pending");
}

/** Update a single cell value. */
export async function updateCell(
  table: string,
  pk: Record<string, string>,
  column: string,
  value: string,
): Promise<UpdateResult> {
  return fetchJson<UpdateResult>(`/api/update/${table}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pk, column, value }),
  });
}

/** Fetch Canvas preview (dry-run comparison with live Canvas). */
export async function fetchCanvasPreview(): Promise<PreviewData> {
  const data = await fetchJson<{ ok: boolean } & PreviewData>(
    "/api/canvas/preview",
    { method: "POST" },
  );
  return data;
}

/** Apply pending changes to Canvas. */
export async function applyCanvasPush(): Promise<{
  ok: boolean;
  results: PushResult[];
}> {
  return fetchJson<{ ok: boolean; results: PushResult[] }>(
    "/api/canvas/apply",
    { method: "POST" },
  );
}

/** Clear all pending changes. */
export async function clearPending(): Promise<void> {
  await fetchJson<{ ok: boolean }>("/api/pending/clear", { method: "POST" });
}

// -- Data parsing --

/** Convert a raw JSON cell value to a display string. */
export function cellToString(val: unknown): string {
  if (val === null || val === undefined) return "";
  if (typeof val === "string") return val;
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (typeof val === "number") {
    // Show integers without decimals
    if (Number.isInteger(val) && Math.abs(val) < 1e10) {
      return String(val);
    }
    return String(val);
  }
  return String(val);
}

/** Parse raw TableData rows into Row records. */
export function parseRows(tableData: TableData): Row[] {
  return tableData.rows.map((rawRow) => {
    const row: Row = {};
    for (let i = 0; i < tableData.columns.length; i++) {
      const col = tableData.columns[i];
      if (col !== undefined) {
        row[col] = cellToString(rawRow[i]);
      }
    }
    return row;
  });
}

/** Check if a row matches a search query (case-insensitive, any column). */
export function matchesSearch(query: string, row: Row): boolean {
  const lower = query.toLowerCase();
  return Object.values(row).some((val) => val.toLowerCase().includes(lower));
}

/** Build CSV content from columns and rows. */
export function buildCsvContent(columns: string[], rows: Row[]): string {
  const escapeCsvField = (val: string): string => {
    if (val.includes(",") || val.includes('"') || val.includes("\n")) {
      return `"${val.replace(/"/g, '""')}"`;
    }
    return val;
  };

  const header = columns.join(",");
  const dataLines = rows.map((row) =>
    columns.map((col) => escapeCsvField(row[col] ?? "")).join(","),
  );
  return [header, ...dataLines].join("\n");
}

/** Trigger a CSV file download in the browser. */
export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export { ApiError };
