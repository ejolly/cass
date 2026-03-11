/**
 * StatusBar — bottom bar showing pending count, table info, and key hints.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { createResource, Show } from "solid-js"
import { isEditable, isPushable } from "@cass/db/catalog.ts"
import { getPendingGradeChanges, getPendingAssignmentChanges } from "@cass/db/sync.ts"
import { activeTable, pendingVersion, toastMessage, type ToastMessage } from "../state.ts"

interface StatusBarProps {
  db: Kysely<Database>
}

export function StatusBar(props: StatusBarProps) {
  const [pendingCount] = createResource(pendingVersion, async () => {
    const [grades, assignments] = await Promise.all([
      getPendingGradeChanges(props.db),
      getPendingAssignmentChanges(props.db),
    ])
    return grades.length + assignments.length
  })

  const tableFlags = () => {
    const t = activeTable()
    const flags: string[] = []
    if (isEditable(t)) flags.push("editable")
    if (isPushable(t)) flags.push("pushable")
    return flags.length > 0 ? flags.join(", ") : "read-only"
  }

  const toast = toastMessage

  return (
    <box height={1} flexDirection="row" paddingX={1} gap={1}>
      <Show when={(pendingCount() ?? 0) > 0}>
        <text fg="#e0af68">
          {`[pending: ${pendingCount()}]`}
        </text>
        <text fg="#414868">│</text>
      </Show>
      <text fg="#565f89">
        {`${activeTable()} (${tableFlags()})`}
      </text>
      <box flexGrow={1} />
      <Show
        when={toast()}
        fallback={
          <text fg="#414868">
            ?:help q:quit Tab:panel /:search s:sort Enter:edit
          </text>
        }
      >
        {(t: () => ToastMessage) => (
          <text fg={t().level === "error" ? "#f7768e" : "#9ece6a"}>
            {t().text}
          </text>
        )}
      </Show>
    </box>
  )
}
