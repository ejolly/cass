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
