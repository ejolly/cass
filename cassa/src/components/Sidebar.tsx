/**
 * Sidebar — grouped table navigation list with cursor.
 */
import { For } from "solid-js"
import { isEditable } from "@cass/db/catalog.ts"
import {
  focusPanel,
  sidebarCursor,
  activeTable,
} from "../state.ts"
import { TABLE_GROUPS, FLAT_TABLES, displayName } from "../catalog.ts"

export function Sidebar() {
  const focused = () => focusPanel() === "sidebar"

  return (
    <box
      width={26}
      border
      borderColor={focused() ? "#7aa2f7" : "#414868"}
      title=" Tables "
      titleAlignment="center"
      flexDirection="column"
      paddingX={1}
    >
      <For each={TABLE_GROUPS}>
        {(group) => {
          const startIdx = FLAT_TABLES.indexOf(group.tables[0]!)
          return (
            <box flexDirection="column">
              <text fg="#565f89">
                <em>{group.label}</em>
              </text>
              <For each={group.tables}>
                {(table, i) => {
                  const idx = startIdx + i()
                  const isActive = () => activeTable() === table
                  const isCursor = () => sidebarCursor() === idx
                  const editable = isEditable(table)

                  return (
                    <box
                      backgroundColor={
                        isActive()
                          ? "#364a82"
                          : isCursor() && focused()
                            ? "#292e42"
                            : undefined
                      }
                    >
                      <text fg={isActive() ? "#7aa2f7" : "#c0caf5"}>
                        {isCursor() && focused() ? "▸ " : "  "}
                        {displayName(table)}
                        {editable ? " *" : ""}
                      </text>
                    </box>
                  )
                }}
              </For>
              <text> </text>
            </box>
          )
        }}
      </For>
    </box>
  )
}
