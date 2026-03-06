<script lang="ts">
  import { app } from "$lib/state.svelte.js";
  import { classifyTable } from "$lib/types.js";
  import { matchesSearch, buildCsvContent, downloadCsv } from "$lib/api.js";
  import { getDisplayedColumns } from "$lib/columns.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";

  function handleSearch(e: Event) {
    const value = (e.target as HTMLInputElement).value;
    app.searchText = value;

    if (!value) {
      app.rows = app.allRows;
    } else {
      app.rows = app.allRows.filter((row) => matchesSearch(value, row));
    }
  }

  function handleExport() {
    if (!app.selectedTable) return;
    const displayedCols = getDisplayedColumns(app.selectedTable, app.columnNames);
    const csv = buildCsvContent(displayedCols, app.rows);
    downloadCsv(`${app.selectedTable}.csv`, csv);
  }

  function openPushModal() {
    app.modal = { kind: "loading" };
  }

  const isEditable = $derived(
    app.schema?.editable && app.selectedTable
      ? classifyTable(app.selectedTable) !== "combined"
      : false
  );

  const rowCountText = $derived(() => {
    const total = app.allRows.length;
    const colCount = app.columnNames.length;
    if (total === 0) return "";

    const base = `${total} rows \u00b7 ${colCount} columns`;
    if (app.searchText) {
      return `${base} (${app.rows.length} matching)`;
    }
    return base;
  });
</script>

<div class="flex h-11 items-center gap-2.5 border-b px-4 py-2">
  <!-- Table name -->
  <span class="text-sm font-semibold">
    {app.selectedTable ?? ""}
  </span>

  <!-- Editable badge -->
  {#if app.schema && app.selectedTable}
    {#if isEditable}
      <Badge variant="outline" class="border-green-600 bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300">
        EDITABLE
      </Badge>
    {:else}
      <Badge variant="secondary">READ-ONLY</Badge>
    {/if}
  {/if}

  <!-- Row count -->
  <span class="text-xs text-muted-foreground">{rowCountText()}</span>

  <!-- Right side -->
  <div class="ml-auto flex items-center gap-2">
    <Input
      id="search-box"
      type="text"
      placeholder="Search rows..."
      class="h-8 w-[200px] text-[13px]"
      value={app.searchText}
      oninput={handleSearch}
    />

    {#if app.selectedTable}
      <Button variant="outline" size="sm" onclick={handleExport}>
        Export CSV
      </Button>
    {/if}

    {#if app.pendingCount > 0}
      <Button variant="outline" size="sm" class="border-primary text-primary" onclick={openPushModal}>
        Push to Canvas
        <Badge class="ml-1 h-5 min-w-5 rounded-full bg-primary px-1 text-[10px] text-primary-foreground">
          {app.pendingCount}
        </Badge>
      </Button>
    {/if}

    {#if app.statusMessage}
      <span
        class="text-xs"
        class:text-green-600={app.statusMessage.level === "success"}
        class:text-red-500={app.statusMessage.level === "error"}
      >
        {app.statusMessage.text}
      </span>
    {/if}
  </div>
</div>
