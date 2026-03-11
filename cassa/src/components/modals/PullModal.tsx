/**
 * PullModal — runs pull and shows streaming progress log.
 */
import type { Kysely } from "kysely"
import type { Database } from "@cass/db/schema.ts"
import type { KyInstance } from "ky"
import type { Config } from "@cass/actions/config.ts"
import { createSignal, createResource, For, Show } from "solid-js"
import { pullAll } from "@cass/actions/pull.ts"
import { setPendingVersion, setTableVersion, showToast } from "../../state.ts"

interface PullModalProps {
  db: Kysely<Database>
  canvasClient: KyInstance | null
  config: Config
}

export function PullModal(props: PullModalProps) {
  const [steps, setSteps] = createSignal<string[]>([])
  const [done, setDone] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)

  createResource(async () => {
    try {
      await pullAll(props.db, props.canvasClient, props.config, (step, detail) => {
        setSteps((prev) => [...prev, `[${step}] ${detail}`])
      })
      setPendingVersion((v) => v + 1)
      setTableVersion((v) => v + 1)
      setDone(true)
      showToast("Pull complete")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setDone(true)
    }
  })

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
        title=" Pull Data "
        titleAlignment="center"
        width={70}
        height={24}
        flexDirection="column"
        paddingX={2}
        paddingY={1}
        backgroundColor="#1a1b26"
      >
        <scrollbox flexGrow={1}>
          <box flexDirection="column">
            <For each={steps()}>
              {(step) => (
                <text fg="#c0caf5">{step}</text>
              )}
            </For>
          </box>
        </scrollbox>

        <Show when={error()}>
          <text fg="#f7768e">{`Error: ${error()}`}</text>
        </Show>

        <Show
          when={done()}
          fallback={<text fg="#e0af68">Pulling...</text>}
        >
          <text fg="#9ece6a">Done</text>
          <text fg="#565f89">[Esc] close</text>
        </Show>
      </box>
    </box>
  )
}
