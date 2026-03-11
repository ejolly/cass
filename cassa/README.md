# cassa-viewer

TUI viewer for cass grading data. Built with [OpenTUI](https://github.com/anomalyco/opentui) + SolidJS.

## Usage

From the project root (requires a `cass.db`):

```bash
cassa view
```

Or run directly:

```bash
cd cassa && bun run dev
```

## Keybindings

| Key | Context | Action |
|-----|---------|--------|
| `j`/`k` | sidebar | Move cursor up/down |
| `l`/`Enter` | sidebar | Select table, focus table |
| `h` | table | Focus sidebar |
| `Tab` | any | Toggle sidebar/table focus |
| `/` | table | Open search |
| `Escape` | search | Clear and close search |
| `q` | any | Quit |

## Architecture

Runs as a subprocess spawned by `cassa view`. Uses Bun workspace path aliases (`@cass/*`) to import directly from the root `src/` package — no duplication of DB or config logic.

```
cassa/src/
  index.tsx              # Entry: reads dbPath, renders <App>
  state.ts               # SolidJS signals (activeTable, focus, search)
  catalog.ts             # Display config (names, column ordering, groups)
  global.d.ts            # TextTable JSX type augmentation
  components/
    App.tsx              # Root layout + keyboard router
    Sidebar.tsx          # Grouped table navigation
    Toolbar.tsx          # Table name, metadata, search input
    TableView.tsx        # Data table via TextTableRenderable
```
