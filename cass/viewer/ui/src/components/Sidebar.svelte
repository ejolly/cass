<script lang="ts">
  import { app } from "$lib/state.svelte.js";
  import { classifyTable, type TableInfo, type TableSource } from "$lib/types.js";
  import { cn } from "$lib/utils.js";
  import * as api from "$lib/api.js";
  import { Separator } from "$lib/components/ui/separator/index.js";

  async function selectTable(name: string) {
    if (app.selectedTable === name) return;

    app.selectedTable = name;
    app.searchText = "";
    app.error = null;
    app.editing = null;

    try {
      const { schema, data } = await api.fetchSchemaAndData(name);
      app.schema = schema;
      app.columnNames = data.columns;
      app.columnTypes = data.types;
      const rows = api.parseRows(data);
      app.allRows = rows;
      app.rows = rows;
    } catch (e) {
      app.error = e instanceof Error ? e.message : String(e);
    }
  }

  function groupTables(tables: TableInfo[]): { label: string; source: TableSource; items: TableInfo[] }[] {
    const combined = tables.filter((t) => classifyTable(t.name) === "combined");
    const canvas = tables.filter((t) => classifyTable(t.name) === "canvas");
    const github = tables.filter((t) => classifyTable(t.name) === "github");

    return [
      { label: "COMBINED DATA", source: "combined" as const, items: combined },
      { label: "CANVAS LMS", source: "canvas" as const, items: canvas },
      { label: "GITHUB CLASSROOM", source: "github" as const, items: github },
    ].filter((g) => g.items.length > 0);
  }

  const groups = $derived(groupTables(app.tables));
</script>

{#if !app.sidebarCollapsed}
  <aside class="flex h-full w-[230px] flex-col border-r bg-sidebar text-sidebar-foreground">
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-4 py-3">
      <span class="text-sm font-bold tracking-wider text-muted-foreground">CASS</span>
      <button
        class="rounded p-1 text-lg text-muted-foreground hover:bg-sidebar-accent"
        onclick={() => (app.sidebarCollapsed = true)}
      >
        &#8249;
      </button>
    </div>

    <!-- Table groups -->
    <nav class="flex-1 overflow-y-auto py-1">
      {#each groups as group, i}
        {#if i > 0}
          <Separator class="my-1" />
        {/if}
        <div class="px-4 pb-1 pt-3">
          <span class="text-[10px] font-semibold tracking-wider text-muted-foreground">
            {group.label}
          </span>
        </div>
        {#each group.items as table}
          <button
            class={cn(
              "w-full px-4 py-2 text-left font-mono text-[13px]",
              app.selectedTable === table.name
                ? "bg-primary text-primary-foreground"
                : "hover:bg-sidebar-accent"
            )}
            onclick={() => selectTable(table.name)}
          >
            {table.name}
          </button>
        {/each}
      {/each}
    </nav>
  </aside>
{/if}
