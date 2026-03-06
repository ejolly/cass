/** Table metadata from /api/tables. */
export type TableInfo = {
  name: string;
  type: "table" | "view";
};

/** Column schema from /api/schema/{table}. */
export type ColumnSchema = {
  name: string;
  type: string;
  nullable: boolean;
};

/** Schema response from /api/schema/{table}. */
export type TableSchema = {
  table: string;
  columns: ColumnSchema[];
  primary_keys: string[];
  editable: boolean;
  canvas_pushable: string[];
};

/** Data response from /api/table/{table}. */
export type TableData = {
  table: string;
  columns: string[];
  types: string[];
  rows: unknown[][];
};

/** A row is a record from column name to string value. */
export type Row = Record<string, string>;

/** Data source classification for sidebar grouping. */
export type TableSource = "combined" | "canvas" | "github";

/** Classify a table name by its prefix. */
export function classifyTable(name: string): TableSource {
  if (name.startsWith("canvas_")) return "canvas";
  if (name.startsWith("gh_")) return "github";
  return "combined";
}

/** Status severity level. */
export type StatusLevel = "success" | "error";

/** A transient status message shown in the toolbar. */
export type StatusMessage = {
  text: string;
  level: StatusLevel;
};

/** State for the inline cell editor. */
export type EditState = {
  column: string;
  value: string;
  originalValue: string;
  pk: Record<string, string>;
};

/** A single change in the Canvas preview diff. */
export type CanvasChange = {
  table: string;
  name: string;
  column: string;
  live: string | null;
  current: string | null;
  conflict: boolean;
  error: string | null;
};

/** Preview data returned from /api/canvas/preview. */
export type PreviewData = {
  changes: CanvasChange[];
  has_conflicts: boolean;
  has_errors: boolean;
};

/** Result of a single push operation from /api/canvas/apply. */
export type PushResult = {
  ok: boolean;
  canvas_id?: number;
  error?: string;
};

/**
 * Canvas push modal state machine.
 *
 * Discriminated union — each variant carries only the data relevant to that state.
 * ModalClosed → ModalLoading → ModalPreview → ModalPushing → ModalClosed
 *                                                          ↘ ModalResults
 */
export type ModalState =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "preview"; data: PreviewData }
  | { kind: "pushing"; data: PreviewData }
  | { kind: "results"; results: PushResult[] }
  | { kind: "error"; message: string };

/** Cell update response from /api/update/{table}. */
export type UpdateResult = {
  ok: boolean;
  error?: string;
  old_value?: unknown;
  pending_count?: number;
};

/** Pending changes summary from /api/pending. */
export type PendingSummary = {
  ok: boolean;
  count: number;
  changes: {
    table: string;
    pk_column: string;
    pk_value: string;
    row_name: string;
    column: string;
    baseline: unknown;
    current: unknown;
  }[];
};
