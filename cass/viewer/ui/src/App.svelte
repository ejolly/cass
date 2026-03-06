<script lang="ts">
  import { app } from "$lib/state.svelte.js";
  import * as api from "$lib/api.js";
  import { classifyTable } from "$lib/types.js";
  import Sidebar from "./components/Sidebar.svelte";
  import Toolbar from "./components/Toolbar.svelte";
  import EditBar from "./components/EditBar.svelte";
  import DataGrid from "./components/DataGrid.svelte";
  import PushModal from "./components/PushModal.svelte";
  import { Toaster } from "$lib/components/ui/sonner/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  // Load initial data
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
        // Trigger table selection via same logic as sidebar
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

  // Keyboard shortcuts
  function handleKeydown(e: KeyboardEvent) {
    // Cmd/Ctrl+K → focus search
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      document.getElementById("search-box")?.focus();
      return;
    }

    // Escape → close modal > cancel edit
    if (e.key === "Escape") {
      if (app.modal.kind !== "closed") {
        app.modal = { kind: "closed" };
      } else if (app.editing) {
        app.editing = null;
      }
    }
  }

  // Dark mode: apply class to document
  $effect(() => {
    if (app.darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  });

  // Watch for system dark mode changes
  $effect(() => {
    const mq = globalThis.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const handler = (e: MediaQueryListEvent) => { app.darkMode = e.matches; };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  });
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="flex h-screen w-screen overflow-hidden bg-background text-foreground">
  <Sidebar />

  <!-- Sidebar toggle when collapsed -->
  {#if app.sidebarCollapsed}
    <Button
      variant="outline"
      size="icon"
      class="absolute left-2 top-10 z-20 h-7 w-7"
      onclick={() => (app.sidebarCollapsed = false)}
    >
      &#8250;
    </Button>
  {/if}

  <main class="flex flex-1 flex-col overflow-hidden">
    <Toolbar />
    <EditBar />
    <DataGrid />
  </main>
</div>

<PushModal />
<Toaster />
