/**
 * Reactive app state — SolidJS signals for the TUI viewer.
 */
import { createSignal } from "solid-js"
import type { ViewerTableName } from "@cass/db/catalog.ts"

// ─── Active table ────────────────────────────────────────────────────

const [activeTable, setActiveTable] = createSignal<ViewerTableName>("canvas_submissions")
export { activeTable, setActiveTable }

// ─── Focus panel ─────────────────────────────────────────────────────

export type FocusPanel = "sidebar" | "table"
const [focusPanel, setFocusPanel] = createSignal<FocusPanel>("sidebar")
export { focusPanel, setFocusPanel }

// ─── Sidebar cursor ──────────────────────────────────────────────────

const [sidebarCursor, setSidebarCursor] = createSignal(0)
export { sidebarCursor, setSidebarCursor }

// ─── Search ──────────────────────────────────────────────────────────

const [searchQuery, setSearchQuery] = createSignal("")
export { searchQuery, setSearchQuery }

const [searchFocused, setSearchFocused] = createSignal(false)
export { searchFocused, setSearchFocused }

// ─── Table cursor ────────────────────────────────────────────────────

const [rowCursor, setRowCursor] = createSignal(0)
export { rowCursor, setRowCursor }

const [colCursor, setColCursor] = createSignal(0)
export { colCursor, setColCursor }

// ─── Editing ─────────────────────────────────────────────────────────

export interface EditingCell {
  row: number
  col: number
  value: string
}

const [editingCell, setEditingCell] = createSignal<EditingCell | null>(null)
export { editingCell, setEditingCell }

// ─── Modals ──────────────────────────────────────────────────────────

export type ModalType = "push" | "revert" | "pull" | null
const [activeModal, setActiveModal] = createSignal<ModalType>(null)
export { activeModal, setActiveModal }

// ─── Sort ────────────────────────────────────────────────────────────

export interface SortState {
  column: string
  dir: "asc" | "desc"
}

const [sortState, setSortState] = createSignal<SortState | null>(null)
export { sortState, setSortState }

// ─── Version counters (trigger re-queries) ───────────────────────────

const [pendingVersion, setPendingVersion] = createSignal(0)
export { pendingVersion, setPendingVersion }

const [tableVersion, setTableVersion] = createSignal(0)
export { tableVersion, setTableVersion }

// ─── Toast ───────────────────────────────────────────────────────────

export interface ToastMessage {
  text: string
  level: "info" | "error"
}

const [toastMessage, setToastMessage] = createSignal<ToastMessage | null>(null)
export { toastMessage, setToastMessage }

let toastTimer: ReturnType<typeof setTimeout> | null = null

export function showToast(text: string, level: "info" | "error" = "info"): void {
  if (toastTimer) clearTimeout(toastTimer)
  setToastMessage({ text, level })
  toastTimer = setTimeout(() => setToastMessage(null), 3000)
}
