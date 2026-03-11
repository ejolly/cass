/**
 * TableView — data table display with cursor, sorting, inline editing, and mouse support.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { createResource, createMemo, createEffect, For, Show } from "solid-js"
import {
  activeTable, searchQuery, tableVersion,
  rowCursor, setRowCursor, colCursor, setColCursor,
  sortState, editingCell, setEditingCell,
  setFocusPanel,
} from "../state.ts"
import { setTableDataRef, getEditCommitRef } from "./App.tsx"
import { getVisibleColumns, getDisplayHeader } from "../catalog.ts"
import { getAllRows, getTableColumns } from "@cass/db/introspection.ts"

interface TableViewProps {
  db: Kysely<Database>
}

// ─── Constants ──────────────────────────────────────────────────────

const HEADER_FG = "#7aa2f7"
const CELL_FG = "#c0caf5"
const BORDER_COLOR = "#414868"
const CURSOR_ROW_BG = "#2d3f76"
const CURSOR_CELL_BG = "#3d4f86"
const MAX_COL_WIDTH = 40
const MIN_COL_WIDTH = 6

// ─── Helpers ────────────────────────────────────────────────────────

function truncate(s: string, maxLen: number): string {
  return s.length > maxLen ? `${s.slice(0, maxLen - 1)}…` : s
}

export interface TableColumn {
  key: string
  header: string
  width: number
  pk: number
}

export interface TableData {
  cols: TableColumn[]
  rows: Record<string, unknown>[]
}

export function TableView(props: TableViewProps) {
  // Load raw data + columns whenever activeTable or tableVersion changes
  const source = () => [activeTable(), tableVersion()] as const
  const [tableData] = createResource(source, async ([table]) => {
    const [rows, colInfo] = await Promise.all([
      getAllRows(props.db, table),
      getTableColumns(props.db, table),
    ])
    const allCols = colInfo.map((c) => c.name)
    const pkMap = new Map(colInfo.map((c) => [c.name, c.pk]))
    return { rows, allCols, pkMap }
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

  // Sort rows
  const sortedRows = createMemo(() => {
    const rows = filteredRows()
    const sort = sortState()
    if (!sort) return rows
    return [...rows].sort((a, b) => {
      const va = a[sort.column]
      const vb = b[sort.column]
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const cmp = String(va).localeCompare(String(vb), undefined, { numeric: true })
      return sort.dir === "asc" ? cmp : -cmp
    })
  })

  // Compute table layout: columns with headers + widths
  const table = createMemo<TableData | undefined>(() => {
    const colKeys = columns()
    const rows = sortedRows()
    if (colKeys.length === 0) return undefined

    const tbl = activeTable()
    const data = tableData()
    const cols: TableColumn[] = colKeys.map((key) => {
      const header = getDisplayHeader(tbl, key)
      const maxCell = rows.reduce((max, row) => {
        const len = String(row[key] ?? "").length
        return len > max ? len : max
      }, 0)
      const width = Math.min(Math.max(Math.max(header.length, maxCell) + 2, MIN_COL_WIDTH), MAX_COL_WIDTH)
      const pk = data?.pkMap.get(key) ?? 0
      return { key, header, width, pk }
    })

    return { cols, rows }
  })

  // Reset cursors when table changes
  createEffect(() => {
    activeTable()
    setRowCursor(0)
    setColCursor(0)
  })

  // Expose table data to App for keyboard handlers
  setTableDataRef(table)

  return (
    <scrollbox flexGrow={1} focused>
      <Show
        when={table()}
        fallback={
          <box flexGrow={1} justifyContent="center" alignItems="center">
            <text fg="#565f89">
              {tableData.loading ? "Loading..." : "No data"}
            </text>
          </box>
        }
      >
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
            <Show
              when={t().rows.length > 0}
              fallback={
                <box paddingX={1} paddingY={1}>
                  <text fg="#565f89">
                    {searchQuery() ? "No matching rows" : "Empty table"}
                  </text>
                </box>
              }
            >
              <For each={t().rows}>
                {(row, rowIdx) => {
                  const isRowCursor = () => rowCursor() === rowIdx()

                  return (
                    <box
                      flexDirection="row"
                      backgroundColor={
                        isRowCursor()
                          ? CURSOR_ROW_BG
                          : rowIdx() % 2 === 1
                            ? "#1a1b26"
                            : undefined
                      }
                      onMouseDown={() => {
                        setRowCursor(rowIdx())
                        setFocusPanel("table")
                      }}
                    >
                      <For each={t().cols}>
                        {(col, colIdx) => {
                          const isCursorCell = () => isRowCursor() && colCursor() === colIdx()
                          const editing = () => {
                            const e = editingCell()
                            return e && e.row === rowIdx() && e.col === colIdx()
                          }

                          return (
                            <box
                              width={col.width}
                              paddingX={1}
                              backgroundColor={isCursorCell() ? CURSOR_CELL_BG : undefined}
                            >
                              <Show
                                when={editing()}
                                fallback={
                                  <text fg={CELL_FG}>
                                    {truncate(String(row[col.key] ?? ""), col.width - 2)}
                                  </text>
                                }
                              >
                                <input
                                  value={editingCell()!.value}
                                  onInput={(v) =>
                                    setEditingCell((prev) => prev ? { ...prev, value: v } : null)
                                  }
                                  onSubmit={() => getEditCommitRef()?.()}
                                  focused
                                  width={col.width - 2}
                                />
                              </Show>
                            </box>
                          )
                        }}
                      </For>
                    </box>
                  )
                }}
              </For>
            </Show>
          </box>
        )}
      </Show>
    </scrollbox>
  )
}
