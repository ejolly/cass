<script lang="ts">
  import { app } from "$lib/state.svelte.js";
  import { classifyTable, type TableInfo } from "$lib/types.js";
  import * as api from "$lib/api.js";

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

  function groupTables(tables: TableInfo[]) {
    const combined = tables.filter((t) => classifyTable(t.name) === "combined");
    const canvas = tables.filter((t) => classifyTable(t.name) === "canvas");
    const github = tables.filter((t) => classifyTable(t.name) === "github");
    return [
      { label: "Combined Data", items: combined },
      { label: "Canvas LMS", items: canvas },
      { label: "GitHub Classroom", items: github },
    ].filter((g) => g.items.length > 0);
  }

  const groups = $derived(groupTables(app.tables));
</script>

{#if !app.sidebarCollapsed}
  <aside class="flex h-full w-56 shrink-0 flex-col border-r border-base-300 bg-base-200">
    <div class="flex items-center justify-between border-b border-base-300 px-4 py-3">
      <span class="text-xs font-bold tracking-widest opacity-60">CASS</span>
      <button
        class="btn btn-ghost btn-xs"
        onclick={() => (app.sidebarCollapsed = true)}
      >&#8249;</button>
    </div>

    <nav class="flex-1 overflow-y-auto">
      <ul class="menu menu-sm">
        {#each groups as group}
          <li class="menu-title">{group.label}</li>
          {#each group.items as table}
            <li>
              <button
                class="font-mono text-xs"
                class:active={app.selectedTable === table.name}
                onclick={() => selectTable(table.name)}
              >{table.name}</button>
            </li>
          {/each}
        {/each}
      </ul>
    </nav>
  </aside>
{/if}
