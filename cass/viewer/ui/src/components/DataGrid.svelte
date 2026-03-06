<script lang="ts">
  import { app, setStatus } from "$lib/state.svelte.js";
  import { classifyTable, type Row } from "$lib/types.js";
  import { getDisplayedColumns } from "$lib/columns.js";
  import * as api from "$lib/api.js";
  import { createGrid, ModuleRegistry, AllCommunityModule, type GridApi, type GridOptions, type CellValueChangedEvent } from "ag-grid-community";
  import "ag-grid-community/styles/ag-grid.css";
  import "ag-grid-community/styles/ag-theme-alpine.css";

  ModuleRegistry.registerModules([AllCommunityModule]);

  let gridDiv = $state<HTMLDivElement>(undefined!);
  let gridApi: GridApi | null = null;

  const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const gridTheme = isDark ? "ag-theme-alpine-dark" : "ag-theme-alpine";

  const effectiveEditable = $derived(
    app.schema?.editable && app.selectedTable
      ? classifyTable(app.selectedTable) !== "combined"
      : false,
  );

  function isPK(col: string): boolean {
    return app.schema?.primary_keys.includes(col) ?? false;
  }

  function isRealColumn(col: string): boolean {
    return app.schema?.columns.some((c) => c.name === col) ?? false;
  }

  function buildColumnDefs(table: string) {
    const displayedCols = getDisplayedColumns(table, app.columnNames);
    const typeMap: Record<string, string> = {};
    for (let i = 0; i < app.columnNames.length; i++) {
      const name = app.columnNames[i];
      const type = app.columnTypes[i];
      if (name !== undefined && type !== undefined) {
        typeMap[name] = type;
      }
    }

    return displayedCols.map((col) => {
      const pk = isPK(col);
      const colType = typeMap[col] ?? "";
      const def: Record<string, unknown> = {
        field: col,
        headerName: pk ? `${col} (PK)` : col,
        sortable: true,
        filter: true,
        resizable: true,
        editable: effectiveEditable && !pk && isRealColumn(col),
        minWidth: 80,
      };

      if (pk) {
        def.cellStyle = { fontWeight: "500", opacity: "0.6" };
      }

      if (colType.includes("INT")) {
        def.cellEditor = "agNumberCellEditor";
        def.cellEditorParams = { allowDecimals: false };
        def.filter = "agNumberColumnFilter";
      } else if (colType.includes("DOUBLE") || colType.includes("FLOAT")) {
        def.cellEditor = "agNumberCellEditor";
        def.filter = "agNumberColumnFilter";
      } else if (colType === "BOOLEAN") {
        def.cellRenderer = (params: { value: unknown }) => {
          if (params.value === null || params.value === undefined || params.value === "") return "";
          return params.value === "Yes" || params.value === true ? "Yes" : "No";
        };
        def.cellEditor = "agCheckboxCellEditor";
      }

      return def;
    });
  }

  function getRowStyle(params: { data?: Row }) {
    if (
      app.selectedTable === "canvas_assignments" &&
      params.data?.["published"] === "No"
    ) {
      return { opacity: "0.45" };
    }
    return undefined;
  }

  async function handleCellEdit(event: CellValueChangedEvent) {
    if (!app.schema?.editable || !app.selectedTable) return;

    const pk: Record<string, string> = {};
    for (const pkCol of app.schema.primary_keys) {
      pk[pkCol] = event.data[pkCol] ?? "";
    }

    try {
      const result = await api.updateCell(
        app.selectedTable,
        pk,
        event.colDef.field!,
        event.newValue,
      );

      if (result.ok) {
        if (result.pending_count !== undefined) app.pendingCount = result.pending_count;
        setStatus("Saved", "success");
        event.api.flashCells({
          rowNodes: [event.node],
          columns: [event.colDef.field!],
          flashDuration: 300,
          fadeDuration: 200,
        });
        // Refresh table data to get server-side state
        const { schema, data } = await api.fetchSchemaAndData(app.selectedTable);
        app.schema = schema;
        app.columnNames = data.columns;
        app.columnTypes = data.types;
        const rows = api.parseRows(data);
        app.allRows = rows;
        app.rows = app.searchText
          ? rows.filter((r) => api.matchesSearch(app.searchText, r))
          : rows;
      } else {
        setStatus(result.error ?? "Update failed", "error");
        // Revert
        event.data[event.colDef.field!] = event.oldValue;
        event.api.refreshCells({
          rowNodes: [event.node],
          columns: [event.colDef.field!],
        });
      }
    } catch {
      setStatus("Network error", "error");
      event.data[event.colDef.field!] = event.oldValue;
      event.api.refreshCells({
        rowNodes: [event.node],
        columns: [event.colDef.field!],
      });
    }
  }

  function createOrUpdateGrid() {
    if (!app.selectedTable || !gridDiv) return;

    const columnDefs = buildColumnDefs(app.selectedTable);
    const rowData = app.rows.map((row) => ({ ...row }));

    if (gridApi) {
      gridApi.destroy();
      gridApi = null;
    }

    const gridOptions: GridOptions = {
      columnDefs,
      rowData,
      defaultColDef: {
        sortable: true,
        resizable: true,
      },
      animateRows: false,
      singleClickEdit: false,
      stopEditingWhenCellsLoseFocus: true,
      getRowStyle,
      onCellValueChanged: handleCellEdit,
      onFirstDataRendered: (params) => {
        params.api.autoSizeAllColumns();
      },
    };

    gridApi = createGrid(gridDiv, gridOptions);
  }

  // Rebuild grid when table selection changes (schema + rows arrive together)
  let lastTable = $state<string | null>(null);
  let lastRowCount = $state(-1);

  $effect(() => {
    const table = app.selectedTable;
    const rowCount = app.rows.length;
    const colCount = app.columnNames.length;
    // Track dependencies
    void colCount;

    if (table && gridDiv && (table !== lastTable || rowCount !== lastRowCount)) {
      lastTable = table;
      lastRowCount = rowCount;
      // Use tick to ensure DOM is ready
      queueMicrotask(createOrUpdateGrid);
    }
  });

  // Sync search filter to AG Grid's quick filter
  $effect(() => {
    const search = app.searchText;
    if (gridApi) {
      gridApi.setGridOption("quickFilterText", search);
    }
  });
</script>

{#if app.error}
  <div class="flex flex-1 items-center justify-center text-error">{app.error}</div>
{:else if !app.selectedTable}
  <div class="flex flex-1 flex-col items-center justify-center gap-2 opacity-50">
    <p class="text-sm">Select a table from the sidebar</p>
    <p class="text-xs">
      Use <kbd class="kbd kbd-xs">{navigator.platform?.includes("Mac") ? "\u2318" : "Ctrl"}</kbd>+<kbd class="kbd kbd-xs">K</kbd> to search
    </p>
  </div>
{:else}
  <div class="flex-1 overflow-hidden">
    <div bind:this={gridDiv} class="{gridTheme}" style="height: 100%; width: 100%;"></div>
  </div>
{/if}
