<script lang="ts">
  import { app } from "$lib/state.svelte.js";
  import * as api from "$lib/api.js";
  import { classifyTable } from "$lib/types.js";
  import Sidebar from "./components/Sidebar.svelte";
  import Toolbar from "./components/Toolbar.svelte";
  import DataGrid from "./components/DataGrid.svelte";
  import PushModal from "./components/PushModal.svelte";

  $effect(() => {
    loadInitialData();
  });

  async function loadInitialData() {
    try {
      const [tables, pending] = await Promise.all([
        api.fetchTables(),
        api.fetchPending().catch(() => ({ count: 0 }) as { count: number }),
      ]);

      app.tables = tables;
      app.pendingCount = pending.count;

      // Auto-select first table, preferring combined tables
      const sorted = [...tables].sort((a, b) => {
        const order = { combined: 0, canvas: 1, github: 2 } as const;
        return order[classifyTable(a.name)] - order[classifyTable(b.name)];
      });
      if (sorted[0]) {
        app.selectedTable = sorted[0].name;
        const { schema, data } = await api.fetchSchemaAndData(sorted[0].name);
        app.schema = schema;
        app.columnNames = data.columns;
        app.columnTypes = data.types;
        const rows = api.parseRows(data);
        app.allRows = rows;
        app.rows = rows;
      }
    } catch (e) {
      app.error = e instanceof Error ? e.message : String(e);
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      document.getElementById("search-box")?.focus();
      return;
    }
    if (e.key === "Escape") {
      if (app.modal.kind !== "closed") {
        app.modal = { kind: "closed" };
      } else if (app.editing) {
        app.editing = null;
      }
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="flex h-screen w-screen overflow-hidden bg-base-100">
  <Sidebar />

  {#if app.sidebarCollapsed}
    <button
      class="btn btn-ghost btn-xs absolute left-2 top-2 z-20"
      onclick={() => (app.sidebarCollapsed = false)}
    >&#8250;</button>
  {/if}

  <main class="flex flex-1 flex-col overflow-hidden">
    <Toolbar />
    <DataGrid />
  </main>
</div>

<PushModal />
