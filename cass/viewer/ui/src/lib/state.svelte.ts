/**
 * Global reactive state for the viewer app.
 *
 * Single $state object — imported by components that need shared state.
 */
import type {
  TableInfo,
  TableSchema,
  Row,
  StatusMessage,
  EditState,
  ModalState,
} from "./types.js";

/** The global app state. */
export const app = $state({
  tables: [] as TableInfo[],
  selectedTable: null as string | null,
  schema: null as TableSchema | null,
  rows: [] as Row[],
  allRows: [] as Row[],
  columnNames: [] as string[],
  columnTypes: [] as string[],
  searchText: "",
  sidebarCollapsed: false,
  error: null as string | null,
  pendingCount: 0,
  statusMessage: null as StatusMessage | null,
  editing: null as EditState | null,
  modal: { kind: "closed" } as ModalState,
});

/** Set a status message that auto-clears after a delay. */
export function setStatus(text: string, level: StatusMessage["level"], delayMs = 3000) {
  app.statusMessage = { text, level };
  setTimeout(() => {
    if (app.statusMessage?.text === text) {
      app.statusMessage = null;
    }
  }, delayMs);
}
