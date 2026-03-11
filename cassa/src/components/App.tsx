/**
 * Root component — split layout + global keyboard router + modal overlay.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import type { KyInstance } from "ky"
import type { Config } from "@cass/actions/config.ts"
import { useKeyboard, useRenderer } from "@opentui/solid"
import { Show } from "solid-js"
import { isEditable, getEditableColumns } from "@cass/db/catalog.ts"
import { updateCell, getTableColumns } from "@cass/db/introspection.ts"
import {
  focusPanel, setFocusPanel,
  sidebarCursor, setSidebarCursor,
  activeTable, setActiveTable,
  searchFocused, setSearchFocused,
  setSearchQuery,
  rowCursor, setRowCursor,
  colCursor, setColCursor,
  editingCell, setEditingCell,
  activeModal, setActiveModal,
  sortState, setSortState,
  setPendingVersion, setTableVersion,
  showToast,
} from "../state.ts"
import { FLAT_TABLES } from "../catalog.ts"
import { Sidebar } from "./Sidebar.tsx"
import { Toolbar } from "./Toolbar.tsx"
import { TableView, type TableData } from "./TableView.tsx"
import { StatusBar } from "./StatusBar.tsx"
import { PushModal } from "./modals/PushModal.tsx"
import { RevertModal } from "./modals/RevertModal.tsx"
import { PullModal } from "./modals/PullModal.tsx"
import { exportCsv } from "../export.ts"

export interface AppProps {
  db: Kysely<Database>
  config: Config | null
  canvasClient: KyInstance | null
}

/** Get the current table data from the TableView's rendered state. */
let tableDataRef: (() => TableData | undefined) | null = null
export function setTableDataRef(fn: () => TableData | undefined): void {
  tableDataRef = fn
}

/** Modal confirm callback — set by modal components, called by App keyboard router. */
let modalConfirmRef: (() => void) | null = null
export function setModalConfirmRef(fn: (() => void) | null): void {
  modalConfirmRef = fn
}

/** Edit commit callback — set by App, called by TableView's input onSubmit. */
let editCommitRef: (() => void) | null = null
export function getEditCommitRef(): (() => void) | null {
  return editCommitRef
}

export function App(props: AppProps) {
  const renderer = useRenderer()

  // Wire up edit commit so TableView's input onSubmit can trigger it
  editCommitRef = () => commitEdit(props.db)

  useKeyboard((key) => {
    // ─── Search focused: only Escape escapes ──────────────────
    if (searchFocused()) {
      if (key.name === "escape") {
        setSearchFocused(false)
        setSearchQuery("")
      }
      return
    }

    // ─── Modal active: delegate to modal ──────────────────────
    if (activeModal()) {
      if (key.name === "escape") {
        setActiveModal(null)
        setModalConfirmRef(null)
      } else if (key.name === "return" && modalConfirmRef) {
        modalConfirmRef()
      }
      return
    }

    // ─── Editing cell: Enter commits, Escape cancels ──────────
    if (editingCell()) {
      if (key.name === "return") {
        key.preventDefault()
        commitEdit(props.db)
      } else if (key.name === "escape") {
        key.preventDefault()
        setEditingCell(null)
      }
      return
    }

    // ─── Global keys ─────────────────────────────────────────
    switch (key.name) {
      case "q":
        renderer.destroy()
        return

      case "tab":
        setFocusPanel((p) => (p === "sidebar" ? "table" : "sidebar"))
        return
    }

    // ─── Sidebar keys ────────────────────────────────────────
    if (focusPanel() === "sidebar") {
      switch (key.name) {
        case "j":
        case "down":
          setSidebarCursor((c) => Math.min(c + 1, FLAT_TABLES.length - 1))
          break
        case "k":
        case "up":
          setSidebarCursor((c) => Math.max(c - 1, 0))
          break
        case "l":
        case "right":
        case "return":
          {
            const table = FLAT_TABLES[sidebarCursor()]
            if (table) {
              setActiveTable(table)
              setFocusPanel("table")
            }
          }
          break
      }
      return
    }

    // ─── Table keys ──────────────────────────────────────────
    if (focusPanel() === "table") {
      const td = tableDataRef?.()
      const rowCount = td?.rows.length ?? 0
      const colCount = td?.cols.length ?? 0

      switch (key.name) {
        case "j":
        case "down":
          setRowCursor((c) => Math.min(c + 1, rowCount - 1))
          break

        case "k":
        case "up":
          setRowCursor((c) => Math.max(c - 1, 0))
          break

        case "l":
        case "right":
          setColCursor((c) => Math.min(c + 1, colCount - 1))
          break

        case "h":
        case "left":
          if (colCursor() === 0) {
            setFocusPanel("sidebar")
          } else {
            setColCursor((c) => Math.max(c - 1, 0))
          }
          break

        case "/":
          setSearchFocused(true)
          break

        case "s":
          cycleSortOnCurrentColumn(td)
          break

        case "return":
          beginEdit(td)
          break

        case "p":
          if (key.shift) {
            // Shift+P: pull
            if (props.canvasClient && props.config) {
              setActiveModal("pull")
            } else {
              showToast("Canvas not configured", "error")
            }
          } else {
            // p: push
            if (props.canvasClient) {
              setActiveModal("push")
            } else {
              showToast("Canvas not configured", "error")
            }
          }
          break

        case "r":
          setActiveModal("revert")
          break

        case "e":
          handleExport(td)
          break
      }
    }
  })

  return (
    <box position="relative" flexGrow={1}>
      {/* Main layout */}
      <box flexDirection="row" flexGrow={1}>
        <Sidebar />
        <box flexGrow={1} flexDirection="column">
          <Toolbar db={props.db} />
          <TableView db={props.db} />
          <StatusBar db={props.db} />
        </box>
      </box>

      {/* Modal overlay */}
      <Show when={activeModal() === "push"}>
        <PushModal
          db={props.db}
          canvasClient={props.canvasClient!}
          config={props.config!}
        />
      </Show>
      <Show when={activeModal() === "revert"}>
        <RevertModal db={props.db} />
      </Show>
      <Show when={activeModal() === "pull"}>
        <PullModal
          db={props.db}
          canvasClient={props.canvasClient}
          config={props.config!}
        />
      </Show>
    </box>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────

function cycleSortOnCurrentColumn(td: TableData | undefined): void {
  if (!td) return
  const col = td.cols[colCursor()]
  if (!col) return

  const current = sortState()
  if (!current || current.column !== col.key) {
    setSortState({ column: col.key, dir: "asc" })
  } else if (current.dir === "asc") {
    setSortState({ column: col.key, dir: "desc" })
  } else {
    setSortState(null)
  }
}

function beginEdit(td: TableData | undefined): void {
  if (!td) return
  const table = activeTable()
  if (!isEditable(table)) {
    showToast("Table is read-only", "error")
    return
  }

  const col = td.cols[colCursor()]
  if (!col) return

  const editableCols = getEditableColumns(table)
  if (editableCols && !editableCols.includes(col.key)) {
    showToast(`Column "${col.key}" is not editable`, "error")
    return
  }

  const row = td.rows[rowCursor()]
  if (!row) return

  setEditingCell({
    row: rowCursor(),
    col: colCursor(),
    value: String(row[col.key] ?? ""),
  })
}

async function commitEdit(db: Kysely<Database>): Promise<void> {
  const cell = editingCell()
  if (!cell) return

  const td = tableDataRef?.()
  if (!td) return

  const col = td.cols[cell.col]
  const row = td.rows[cell.row]
  if (!col || !row) {
    setEditingCell(null)
    return
  }

  // Find PK columns
  const pkCols = td.cols.filter((c) => c.pk > 0).sort((a, b) => a.pk - b.pk)
  if (pkCols.length === 0) {
    // Fallback: fetch PK info from DB
    const colInfo = await getTableColumns(db, activeTable())
    const pks = colInfo.filter((c) => c.pk > 0).sort((a, b) => a.pk - b.pk)
    if (pks.length === 0) {
      showToast("Cannot edit: no primary key", "error")
      setEditingCell(null)
      return
    }

    await updateCell(
      db,
      activeTable(),
      pks.map((p) => p.name),
      pks.map((p) => row[p.name] as string | number),
      col.key,
      cell.value || null,
    )
  } else {
    await updateCell(
      db,
      activeTable(),
      pkCols.map((c) => c.key),
      pkCols.map((c) => row[c.key] as string | number),
      col.key,
      cell.value || null,
    )
  }

  setEditingCell(null)
  setPendingVersion((v) => v + 1)
  setTableVersion((v) => v + 1)
  showToast("Cell updated")
}

function handleExport(td: TableData | undefined): void {
  if (!td || td.rows.length === 0) {
    showToast("No data to export", "error")
    return
  }
  const path = exportCsv(td.rows, td.cols.map((c) => c.key), activeTable())
  showToast(`Exported to ${path}`)
}
