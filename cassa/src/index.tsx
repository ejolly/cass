/**
 * TUI viewer entry point — reads dbPath from argv, loads config, renders the app.
 */
import { render } from "@opentui/solid"
import { createDb } from "@cass/db/connection.ts"
import { loadConfig, hasCanvas } from "@cass/actions/config.ts"
import { createCanvasClient, loadCanvasToken } from "@cass/apis/canvas/client.ts"
import type { Config } from "@cass/actions/config.ts"
import type { KyInstance } from "ky"
import { App } from "./components/App.tsx"

const dbPath = process.argv[2]
if (!dbPath) {
  console.error("Usage: cassa-viewer <dbPath>")
  process.exit(1)
}

const db = createDb(dbPath)

let config: Config | null = null
let canvasClient: KyInstance | null = null

try {
  config = await loadConfig()
  if (hasCanvas(config)) {
    const token = await loadCanvasToken(config.root)
    canvasClient = createCanvasClient({ baseUrl: config.canvasBaseUrl, token })
  }
} catch {
  // Config not found or Canvas not configured — viewer works in read-only mode
}

render(() => <App db={db} config={config} canvasClient={canvasClient} />, { exitOnCtrlC: true })
