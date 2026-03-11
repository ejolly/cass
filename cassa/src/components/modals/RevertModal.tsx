/**
 * RevertModal — confirmation dialog to revert all pending changes.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import { createResource, createEffect, onCleanup, Show } from "solid-js"
import { getPendingGradeChanges, getPendingAssignmentChanges, revertGrades, revertAssignments } from "@cass/db/sync.ts"
import { setActiveModal, setPendingVersion, setTableVersion, showToast } from "../../state.ts"
import { setModalConfirmRef } from "../App.tsx"

interface RevertModalProps {
  db: Kysely<Database>
}

export function RevertModal(props: RevertModalProps) {
  const [pending] = createResource(async () => {
    const [grades, assignments] = await Promise.all([
      getPendingGradeChanges(props.db),
      getPendingAssignmentChanges(props.db),
    ])
    return { gradeCount: grades.length, assignmentCount: assignments.length }
  })

  async function doRevert(): Promise<void> {
    const [gradeCount, assignmentCount] = await Promise.all([
      revertGrades(props.db),
      revertAssignments(props.db),
    ])
    const total = gradeCount + assignmentCount
    setPendingVersion((v) => v + 1)
    setTableVersion((v) => v + 1)
    setActiveModal(null)
    setModalConfirmRef(null)
    showToast(`Reverted ${total} change${total !== 1 ? "s" : ""}`)
  }

  const total = () => {
    const p = pending()
    return p ? p.gradeCount + p.assignmentCount : 0
  }

  // Register confirm when pending data loads and total > 0
  createEffect(() => {
    if (total() > 0) {
      setModalConfirmRef(() => doRevert())
    }
  })

  onCleanup(() => setModalConfirmRef(null))

  return (
    <box
      position="absolute"
      left={0}
      top={0}
      width="100%"
      height="100%"
      zIndex={10}
      justifyContent="center"
      alignItems="center"
    >
      <box
        border
        borderColor="#f7768e"
        title=" Revert Changes "
        titleAlignment="center"
        width={50}
        height={10}
        flexDirection="column"
        paddingX={2}
        paddingY={1}
        backgroundColor="#1a1b26"
        justifyContent="center"
        alignItems="center"
      >
        <Show
          when={!pending.loading}
          fallback={<text fg="#565f89">Checking pending changes...</text>}
        >
          <Show
            when={total() > 0}
            fallback={
              <>
                <text fg="#565f89">No pending changes to revert.</text>
                <text> </text>
                <text fg="#565f89">[Esc] close</text>
              </>
            }
          >
            <text fg="#c0caf5">
              {`Revert ${total()} pending change${total() !== 1 ? "s" : ""}?`}
            </text>
            <text> </text>
            <text fg="#565f89">[Enter] confirm  [Esc] cancel</text>
          </Show>
        </Show>
      </box>
    </box>
  )
}
