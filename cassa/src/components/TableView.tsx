/**
 * TableView — data table display using TextTableRenderable.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { type TextChunk, RGBA, TextTableRenderable } from "@opentui/core"
import type { TextTableContent, TextTableCellContent } from "@opentui/core"
import { extend } from "@opentui/solid"
import { createResource, createMemo } from "solid-js"
import { activeTable, searchQuery } from "../state.ts"
import { getVisibleColumns, getDisplayHeader } from "../catalog.ts"
import { getAllRows, getTableColumns } from "@cass/db/introspection.ts"

// Register TextTable as a JSX element
extend({ text_table: TextTableRenderable })

interface TableViewProps {
  db: Kysely<Database>
}

// ─── Helpers ─────────────────────────────────────────────────────────

const HEADER_FG = RGBA.fromHex("#7aa2f7")
const CELL_FG = RGBA.fromHex("#c0caf5")

function cell(s: string, fg?: RGBA): TextTableCellContent {
  return [{ __isChunk: true, text: s, fg: fg ?? CELL_FG } as TextChunk]
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
      Object.values(row).some((v) =>
        String(v ?? "").toLowerCase().includes(q)
      )
    )
  })

  // Build TextTableContent: header row + data rows
  const content = createMemo<TextTableContent>(() => {
    const cols = columns()
    const rows = filteredRows()
    if (cols.length === 0) return []

    const table = activeTable()
    const headerRow: TextTableCellContent[] = cols.map((c) =>
      cell(getDisplayHeader(table, c), HEADER_FG)
    )

    const dataRows: TextTableCellContent[][] = rows.map((row) =>
      cols.map((c) => cell(String(row[c] ?? "")))
    )

    return [headerRow, ...dataRows]
  })

  return (
    <scrollbox flexGrow={1} focused>
      <text_table
        content={content()}
        border
        columnWidthMode="full"
        columnFitter="balanced"
        cellPadding={1}
        borderColor="#414868"
        fg="#c0caf5"
      />
    </scrollbox>
  )
}
