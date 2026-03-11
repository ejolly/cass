/**
 * Toolbar — shows table name, row/col metadata, and search input.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { createResource } from "solid-js"
import {
  activeTable,
  searchQuery, setSearchQuery,
  searchFocused,
} from "../state.ts"
import { displayName } from "../catalog.ts"
import { getAllRows, getTableColumns } from "@cass/db/introspection.ts"

interface ToolbarProps {
  db: Kysely<Database>
}

export function Toolbar(props: ToolbarProps) {
  const [meta] = createResource(activeTable, async (table) => {
    const [rows, cols] = await Promise.all([
      getAllRows(props.db, table),
      getTableColumns(props.db, table),
    ])
    return { rowCount: rows.length, colCount: cols.length }
  })

  return (
    <box height={3} flexDirection="row" paddingX={1} gap={2} alignItems="center">
      <text>
        <strong>{displayName(activeTable())}</strong>
      </text>
      <text fg="#565f89">
        {meta()
          ? `${meta()!.rowCount} rows × ${meta()!.colCount} cols`
          : "loading..."}
      </text>
      <box flexGrow={1} />
      <input
        placeholder="/ search..."
        value={searchQuery()}
        onInput={(v) => setSearchQuery(v)}
        focused={searchFocused()}
        width={24}
      />
    </box>
  )
}
