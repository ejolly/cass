/**
 * PushModal — preview pending changes, push to Canvas, show results.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import type { KyInstance } from "ky"
import type { Config } from "@cass/actions/config.ts"
import { createSignal, createResource, createEffect, onCleanup, For, Show } from "solid-js"
import { getPendingGradeChanges, getPendingAssignmentChanges, snapshotGradesSynced, snapshotAssignmentsSynced } from "@cass/db/sync.ts"
import { buildGradePushData, buildPushPreview, pushGrades, pushAssignments, type PushResult, type PushPreviewItem } from "@cass/apis/canvas/sync.ts"
import { setActiveModal, setPendingVersion, setTableVersion, showToast } from "../../state.ts"
import { setModalConfirmRef } from "../App.tsx"

type Stage = "preview" | "pushing" | "results"

interface PushModalProps {
  db: Kysely<Database>
  canvasClient: KyInstance
  config: Config
}

export function PushModal(props: PushModalProps) {
  const [stage, setStage] = createSignal<Stage>("preview")
  const [results, setResults] = createSignal<PushResult[]>([])
  const [pushStatus, setPushStatus] = createSignal("")

  const [preview] = createResource(async () => {
    const [grades, assignments] = await Promise.all([
      getPendingGradeChanges(props.db),
      getPendingAssignmentChanges(props.db),
    ])

    let gradePreview: PushPreviewItem[] = []
    let skipped = 0
    if (grades.length > 0) {
      const [gradeData, skippedCount] = buildGradePushData(grades)
      skipped = skippedCount
      gradePreview = await buildPushPreview(props.db, gradeData)
    }

    return { grades, assignments, gradePreview, skipped }
  })

  // Register confirm handler
  createEffect(() => {
    const s = stage()
    if (s === "preview") {
      const p = preview()
      const total = p ? p.grades.length + p.assignments.length : 0
      if (total > 0) {
        setModalConfirmRef(() => doPush())
      } else {
        setModalConfirmRef(null)
      }
    } else if (s === "results") {
      setModalConfirmRef(null)
    }
  })

  onCleanup(() => setModalConfirmRef(null))

  async function doPush(): Promise<void> {
    setStage("pushing")
    setModalConfirmRef(null)
    const allResults: PushResult[] = []

    const [grades, assignments] = await Promise.all([
      getPendingGradeChanges(props.db),
      getPendingAssignmentChanges(props.db),
    ])

    if (grades.length > 0) {
      setPushStatus("Pushing grades...")
      const [gradeData] = buildGradePushData(grades)
      const gradeResults = await pushGrades(props.canvasClient, props.config.canvasCourseId, gradeData)
      allResults.push(...gradeResults)
    }

    if (assignments.length > 0) {
      setPushStatus("Pushing assignment updates...")
      const updatesByCanvasId: Record<number, Record<string, unknown>> = {}
      for (const a of assignments) {
        updatesByCanvasId[a.canvas_id] = {
          name: a.name,
          points_possible: a.points_possible,
          due_at: a.due_at,
          published: a.published,
        }
      }
      const assignmentResults = await pushAssignments(props.canvasClient, props.config.canvasCourseId, updatesByCanvasId)
      allResults.push(...assignmentResults)
    }

    await snapshotGradesSynced(props.db)
    await snapshotAssignmentsSynced(props.db)

    setPendingVersion((v) => v + 1)
    setTableVersion((v) => v + 1)
    setResults(allResults)
    setStage("results")
  }

  const succeeded = () => results().filter((r) => r.ok).length
  const failed = () => results().filter((r) => !r.ok).length

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
        borderColor="#7aa2f7"
        title=" Push to Canvas "
        titleAlignment="center"
        width={60}
        height={20}
        flexDirection="column"
        paddingX={2}
        paddingY={1}
        backgroundColor="#1a1b26"
      >
        <Show when={stage() === "preview"}>
          <Show
            when={!preview.loading}
            fallback={<text fg="#565f89">Loading preview...</text>}
          >
            {() => {
              const p = preview()
              if (!p) return <text fg="#565f89">No data</text>
              const total = p.grades.length + p.assignments.length

              return (
                <>
                  <text fg="#c0caf5">
                    <strong>{`${total} pending change${total !== 1 ? "s" : ""}`}</strong>
                  </text>
                  <text> </text>
                  <Show when={p.gradePreview.length > 0}>
                    <text fg="#7aa2f7">Grade changes:</text>
                    <For each={p.gradePreview}>
                      {(item) => (
                        <text fg="#c0caf5">
                          {`  ${item.name}: ${item.count} grade${item.count !== 1 ? "s" : ""}`}
                        </text>
                      )}
                    </For>
                  </Show>
                  <Show when={p.skipped > 0}>
                    <text fg="#e0af68">{`  (${p.skipped} skipped — invalid grades)`}</text>
                  </Show>
                  <Show when={p.assignments.length > 0}>
                    <text fg="#7aa2f7">{`Assignment field changes: ${p.assignments.length}`}</text>
                  </Show>
                  <box flexGrow={1} />
                  <Show
                    when={total > 0}
                    fallback={<text fg="#565f89">Nothing to push. [Esc] close</text>}
                  >
                    <text fg="#565f89">[Enter] push  [Esc] cancel</text>
                  </Show>
                </>
              )
            }}
          </Show>
        </Show>

        <Show when={stage() === "pushing"}>
          <text fg="#e0af68">{pushStatus()}</text>
        </Show>

        <Show when={stage() === "results"}>
          <text fg="#9ece6a">
            <strong>{`Push complete: ${succeeded()} succeeded`}</strong>
          </text>
          <Show when={failed() > 0}>
            <text fg="#f7768e">{`${failed()} failed`}</text>
            <For each={results().filter((r) => !r.ok)}>
              {(r) => (
                <text fg="#f7768e">
                  {`  ${!r.ok ? r.error : ""}`}
                </text>
              )}
            </For>
          </Show>
          <box flexGrow={1} />
          <text fg="#565f89">[Esc] close</text>
        </Show>
      </box>
    </box>
  )
}
