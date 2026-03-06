<script lang="ts">
  import { app, setStatus } from "$lib/state.svelte.js";
  import { classifyTable, type Row } from "$lib/types.js";
  import { getDisplayedColumns } from "$lib/columns.js";
  import * as api from "$lib/api.js";

  let sortCol = $state<string | null>(null);
  let sortDir = $state<"asc" | "desc">("asc");

  const displayedCols = $derived(
    app.selectedTable
      ? getDisplayedColumns(app.selectedTable, app.columnNames)
      : app.columnNames,
  );

  const effectiveEditable = $derived(
    app.schema?.editable && app.selectedTable
      ? classifyTable(app.selectedTable) !== "combined"
      : false,
  );

  const sortedRows = $derived.by(() => {
    if (!sortCol) return app.rows;
    const col = sortCol;
    const dir = sortDir;
    return [...app.rows].sort((a, b) => {
      const av = a[col] ?? "";
      const bv = b[col] ?? "";
      const cmp = av.localeCompare(bv, undefined, { numeric: true });
      return dir === "asc" ? cmp : -cmp;
    });
  });

  function toggleSort(col: string) {
    if (sortCol === col) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortCol = col;
      sortDir = "asc";
    }
  }

  function isPK(col: string): boolean {
    return app.schema?.primary_keys.includes(col) ?? false;
  }

  function isEditableCell(col: string): boolean {
    if (!effectiveEditable || !app.schema) return false;
    if (isPK(col)) return false;
    return app.schema.columns.some((c) => c.name === col);
  }

  function cellKey(row: Row, col: string): string {
    if (!app.schema) return "";
    const pk: Record<string, string> = {};
    for (const pkCol of app.schema.primary_keys) {
      pk[pkCol] = row[pkCol] ?? "";
    }
    return JSON.stringify(pk) + "::" + col;
  }

  function editingKey(): string | null {
    if (!app.editing) return null;
    return JSON.stringify(app.editing.pk) + "::" + app.editing.column;
  }

  function startEdit(row: Row, col: string) {
    if (!isEditableCell(col) || !app.schema) return;
    const pk: Record<string, string> = {};
    for (const pkCol of app.schema.primary_keys) {
      pk[pkCol] = row[pkCol] ?? "";
    }
    app.editing = {
      column: col,
      value: row[col] ?? "",
      originalValue: row[col] ?? "",
      pk,
    };
  }

  async function commitEdit() {
    const ed = app.editing;
    if (!ed || !app.selectedTable) return;
    if (ed.value === ed.originalValue) {
      app.editing = null;
      return;
    }
    const table = app.selectedTable;
    app.editing = null;

    try {
      const result = await api.updateCell(table, ed.pk, ed.column, ed.value);
      if (result.ok) {
        if (result.pending_count !== undefined) app.pendingCount = result.pending_count;
        setStatus("Saved", "success");
        // Refresh table data
        const { schema, data } = await api.fetchSchemaAndData(table);
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
      }
    } catch {
      setStatus("Network error", "error");
    }
  }

  function handleEditKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") commitEdit();
    if (e.key === "Escape") app.editing = null;
  }

  function isUnpublished(row: Row): boolean {
    return app.selectedTable === "canvas_assignments" && row["published"] === "No";
  }

  /** Svelte action: focus and select input on mount. */
  function autofocus(node: HTMLInputElement) {
    node.focus();
    node.select();
  }
</script>

{#if app.error}
  <div class="flex flex-1 items-center justify-center text-error">{app.error}</div>
{:else if !app.selectedTable}
  <div class="flex flex-1 flex-col items-center justify-center gap-2 opacity-50">
    <p class="text-sm">Select a table from the sidebar</p>
    <p class="text-xs">
      Use <kbd class="kbd kbd-xs">{navigator.platform?.includes("Mac") ? "⌘" : "Ctrl"}</kbd>+<kbd class="kbd kbd-xs">K</kbd> to search
    </p>
  </div>
{:else}
  <div class="flex-1 overflow-auto">
    <table class="table table-xs table-pin-rows">
      <thead>
        <tr>
          {#each displayedCols as col}
            <th
              class="cursor-pointer select-none whitespace-nowrap"
              onclick={() => toggleSort(col)}
            >
              {isPK(col) ? `${col} (PK)` : col}
              {#if sortCol === col}
                <span class="ml-0.5">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>
              {/if}
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each sortedRows as row}
          <tr class:opacity-45={isUnpublished(row)}>
            {#each displayedCols as col}
              {@const editing = editingKey() === cellKey(row, col)}
              <td
                class="whitespace-nowrap"
                class:cursor-pointer={isEditableCell(col)}
                class:font-medium={isPK(col)}
                class:opacity-60={isPK(col)}
                onclick={() => { if (!editing) startEdit(row, col); }}
              >
                {#if editing}
                  <input
                    type="text"
                    class="input input-xs input-bordered w-full min-w-16"
                    value={app.editing?.value ?? ""}
                    oninput={(e: Event) => {
                      if (app.editing) app.editing.value = (e.target as HTMLInputElement).value;
                    }}
                    onkeydown={handleEditKeydown}
                    onblur={() => commitEdit()}
                    use:autofocus
                  />
                {:else}
                  {row[col] ?? ""}
                {/if}
              </td>
            {/each}
          </tr>
        {:else}
          <tr>
            <td colspan={displayedCols.length} class="py-8 text-center opacity-50">
              No results.
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
