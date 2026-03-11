/**
 * TableView — data table display using box + text layout.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { createResource, createMemo, For, Show } from "solid-js"
import { activeTable, searchQuery } from "../state.ts"
import { getVisibleColumns, getDisplayHeader } from "../catalog.ts"
import { getAllRows, getTableColumns } from "@cass/db/introspection.ts"

interface TableViewProps {
  db: Kysely<Database>
}

// ─── Constants ──────────────────────────────────────────────────────

const HEADER_FG = "#7aa2f7"
const CELL_FG = "#c0caf5"
const BORDER_COLOR = "#414868"
const MAX_COL_WIDTH = 40
const MIN_COL_WIDTH = 6

// ─── Helpers ────────────────────────────────────────────────────────

function truncate(s: string, maxLen: number): string {
  return s.length > maxLen ? `${s.slice(0, maxLen - 1)}…` : s
}

interface TableColumn {
  key: string
  header: string
  width: number
}

interface TableData {
  cols: TableColumn[]
  rows: Record<string, unknown>[]
}

export function TableView(props: TableViewProps) {
  // Load raw data + columns whenever activeTable changes
  const [tableData] = createResource(activeTable, async (table) => {
    const [rows, colInfo] = await Promise.all([
      getAllRows(props.db, table),
      getTableColumns(props.db, table),
    ])
    const allCols = colInfo.map((c) => c.name)
    return { rows, allCols }
  })

  // Compute visible + ordered columns
  const columns = createMemo(() => {
    const data = tableData()
    if (!data) return []
    return getVisibleColumns(activeTable(), data.allCols)
  })

  // Filter rows by search query
  const filteredRows = createMemo(() => {
    const data = tableData()
    if (!data) return []
    const q = searchQuery().toLowerCase()
    if (!q) return data.rows
    return data.rows.filter((row) =>
      Object.values(row).some((v) => String(v ?? "").toLowerCase().includes(q))
    )
  })

  // Compute table layout: columns with headers + widths, filtered rows
  const table = createMemo<TableData | undefined>(() => {
    const colKeys = columns()
    const rows = filteredRows()
    if (colKeys.length === 0) return undefined

    const tbl = activeTable()
    const cols: TableColumn[] = colKeys.map((key) => {
      const header = getDisplayHeader(tbl, key)
      const maxCell = rows.reduce((max, row) => {
        const len = String(row[key] ?? "").length
        return len > max ? len : max
      }, 0)
      const width = Math.min(Math.max(Math.max(header.length, maxCell) + 2, MIN_COL_WIDTH), MAX_COL_WIDTH)
      return { key, header, width }
    })

    return { cols, rows }
  })

  return (
    <scrollbox flexGrow={1} focused>
      <Show when={table()}>
        {(t: () => TableData) => (
          <box flexDirection="column">
            {/* Header row */}
            <box flexDirection="row">
              <For each={t().cols}>
                {(col) => (
                  <box width={col.width} paddingX={1}>
                    <text fg={HEADER_FG}>
                      <strong>{truncate(col.header, col.width - 2)}</strong>
                    </text>
                  </box>
                )}
              </For>
            </box>
            {/* Separator */}
            <box height={1}>
              <text fg={BORDER_COLOR}>
                {"─".repeat(t().cols.reduce((sum, c) => sum + c.width, 0))}
              </text>
            </box>
            {/* Data rows */}
            <For each={t().rows}>
              {(row, rowIdx) => (
                <box
                  flexDirection="row"
                  backgroundColor={rowIdx() % 2 === 1 ? "#1a1b26" : undefined}
                >
                  <For each={t().cols}>
                    {(col) => (
                      <box width={col.width} paddingX={1}>
                        <text fg={CELL_FG}>
                          {truncate(String(row[col.key] ?? ""), col.width - 2)}
                        </text>
                      </box>
                    )}
                  </For>
                </box>
              )}
            </For>
          </box>
        )}
      </Show>
    </scrollbox>
  )
}
