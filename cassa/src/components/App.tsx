/**
 * Root component — split layout + global keyboard router.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { useKeyboard, useRenderer } from "@opentui/solid"
import {
  focusPanel, setFocusPanel,
  sidebarCursor, setSidebarCursor,
  activeTable, setActiveTable,
  searchFocused, setSearchFocused,
  setSearchQuery,
} from "../state.ts"
import { FLAT_TABLES } from "../catalog.ts"
import { Sidebar } from "./Sidebar.tsx"
import { Toolbar } from "./Toolbar.tsx"
import { TableView } from "./TableView.tsx"

interface AppProps {
  db: Kysely<Database>
}

export function App(props: AppProps) {
  const renderer = useRenderer()

  useKeyboard((key) => {
    // Let the input component handle keys when search is focused
    if (searchFocused()) {
      if (key.name === "escape") {
        setSearchFocused(false)
        setSearchQuery("")
      }
      return
    }

    switch (key.name) {
      case "q":
        renderer.destroy()
        break

      case "tab":
        setFocusPanel((p) => (p === "sidebar" ? "table" : "sidebar"))
        break

      case "j":
      case "down":
        if (focusPanel() === "sidebar") {
          setSidebarCursor((c) => Math.min(c + 1, FLAT_TABLES.length - 1))
        }
        break

      case "k":
      case "up":
        if (focusPanel() === "sidebar") {
          setSidebarCursor((c) => Math.max(c - 1, 0))
        }
        break

      case "l":
      case "right":
      case "enter":
        if (focusPanel() === "sidebar") {
          const table = FLAT_TABLES[sidebarCursor()]
          if (table) {
            setActiveTable(table)
            setFocusPanel("table")
          }
        }
        break

      case "h":
      case "left":
        if (focusPanel() === "table") {
          setFocusPanel("sidebar")
        }
        break

      case "/":
        if (focusPanel() === "table") {
          setSearchFocused(true)
        }
        break
    }
  })

  return (
    <box flexDirection="row" flexGrow={1}>
      <Sidebar />
      <box flexGrow={1} flexDirection="column">
        <Toolbar db={props.db} />
        <TableView db={props.db} />
      </box>
    </box>
  )
}
