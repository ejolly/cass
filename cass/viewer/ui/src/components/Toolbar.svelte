<script lang="ts">
  import { app } from "$lib/state.svelte.js";
  import { classifyTable } from "$lib/types.js";
  import { matchesSearch, buildCsvContent, downloadCsv } from "$lib/api.js";
  import { getDisplayedColumns } from "$lib/columns.js";

  function handleSearch(e: Event) {
    const value = (e.target as HTMLInputElement).value;
    app.searchText = value;
    app.rows = value
      ? app.allRows.filter((row) => matchesSearch(value, row))
      : app.allRows;
  }

  function handleExport() {
    if (!app.selectedTable) return;
    const cols = getDisplayedColumns(app.selectedTable, app.columnNames);
    const csv = buildCsvContent(cols, app.rows);
    downloadCsv(`${app.selectedTable}.csv`, csv);
  }

  const isEditable = $derived(
    app.schema?.editable && app.selectedTable
      ? classifyTable(app.selectedTable) !== "combined"
      : false,
  );

  const rowCountText = $derived.by(() => {
    if (!app.allRows.length) return "";
    const base = `${app.allRows.length} rows \u00b7 ${app.columnNames.length} columns`;
    return app.searchText ? `${base} (${app.rows.length} matching)` : base;
  });
</script>

<div class="flex items-center gap-2.5 border-b border-base-300 px-4 py-2">
  <span class="text-sm font-semibold">{app.selectedTable ?? ""}</span>

  {#if app.schema && app.selectedTable}
    {#if isEditable}
      <span class="badge badge-success badge-sm">EDITABLE</span>
    {:else}
      <span class="badge badge-ghost badge-sm">READ-ONLY</span>
    {/if}
  {/if}

  <span class="text-xs opacity-50">{rowCountText}</span>

  <div class="ml-auto flex items-center gap-2">
    <input
      id="search-box"
      type="text"
      placeholder="Search rows..."
      class="input input-bordered input-sm w-48 text-xs"
      value={app.searchText}
      oninput={handleSearch}
    />

    {#if app.selectedTable}
      <button class="btn btn-outline btn-sm" onclick={handleExport}>Export CSV</button>
    {/if}

    {#if app.pendingCount > 0}
      <button
        class="btn btn-primary btn-sm"
        onclick={() => (app.modal = { kind: "loading" })}
      >
        Push to Canvas
        <span class="badge badge-sm">{app.pendingCount}</span>
      </button>
    {/if}

    {#if app.statusMessage}
      <span
        class="text-xs"
        class:text-success={app.statusMessage.level === "success"}
        class:text-error={app.statusMessage.level === "error"}
      >
        {app.statusMessage.text}
      </span>
    {/if}
  </div>
</div>
