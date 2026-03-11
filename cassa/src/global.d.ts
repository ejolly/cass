import type { TextTableRenderable } from "@opentui/core"

declare module "@opentui/solid" {
  interface OpenTUIComponents {
    text_table: typeof TextTableRenderable
  }
}
