/**
 * HelpModal — keyboard shortcut reference.
 */
import { For } from "solid-js"

interface ShortcutGroup {
  label: string
  shortcuts: { key: string; desc: string }[]
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    label: "Navigation",
    shortcuts: [
      { key: "j / ↓", desc: "Move down" },
      { key: "k / ↑", desc: "Move up" },
      { key: "h / ←", desc: "Move left / go to sidebar" },
      { key: "l / →", desc: "Move right / select table" },
      { key: "Tab", desc: "Switch panel (sidebar ↔ table)" },
      { key: "Enter", desc: "Select table / edit cell" },
    ],
  },
  {
    label: "Table",
    shortcuts: [
      { key: "/", desc: "Search rows" },
      { key: "s", desc: "Cycle sort on column" },
      { key: "e", desc: "Export table as CSV" },
    ],
  },
  {
    label: "Editing",
    shortcuts: [
      { key: "Enter", desc: "Begin edit / save edit" },
      { key: "Escape", desc: "Cancel edit / close modal" },
    ],
  },
  {
    label: "Actions",
    shortcuts: [
      { key: "p", desc: "Push to Canvas" },
      { key: "P", desc: "Pull data" },
      { key: "r", desc: "Revert changes" },
    ],
  },
  {
    label: "General",
    shortcuts: [
      { key: "?", desc: "Show this help" },
      { key: "q", desc: "Quit" },
    ],
  },
]

export function HelpModal() {
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
        title=" Keyboard Shortcuts "
        titleAlignment="center"
        width={44}
        height={26}
        flexDirection="column"
        paddingX={2}
        paddingY={1}
        backgroundColor="#1a1b26"
      >
        <For each={SHORTCUT_GROUPS}>
          {(group) => (
            <box flexDirection="column">
              <text fg="#7aa2f7">
                <strong>{group.label}</strong>
              </text>
              <For each={group.shortcuts}>
                {(s) => (
                  <box flexDirection="row">
                    <box width={14}>
                      <text fg="#e0af68">{`  ${s.key}`}</text>
                    </box>
                    <text fg="#c0caf5">{s.desc}</text>
                  </box>
                )}
              </For>
              <text> </text>
            </box>
          )}
        </For>
        <text fg="#565f89">[Esc] close</text>
      </box>
    </box>
  )
}
