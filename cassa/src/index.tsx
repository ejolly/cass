/**
 * TUI viewer entry point — reads dbPath from argv, renders the app.
 */
import { render } from "@opentui/solid"
import { createDb } from "@cass/db/connection.ts"
import { App } from "./components/App.tsx"

const dbPath = process.argv[2]
if (!dbPath) {
  console.error("Usage: cassa-viewer <dbPath>")
  process.exit(1)
}

const db = createDb(dbPath)

render(() => <App db={db} />, { exitOnCtrlC: true })
