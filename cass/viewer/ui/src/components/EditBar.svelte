<script lang="ts">
  import { app, setStatus } from "$lib/state.svelte.js";
  import * as api from "$lib/api.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";

  let inputEl: HTMLInputElement | undefined = $state();

  $effect(() => {
    if (app.editing && inputEl) {
      inputEl.focus();
    }
  });

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
        if (result.pending_count !== undefined) {
          app.pendingCount = result.pending_count;
        }
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

  function cancelEdit() {
    app.editing = null;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") commitEdit();
    if (e.key === "Escape") cancelEdit();
  }
</script>

{#if app.editing}
  <div class="flex items-center gap-2.5 border-b border-primary bg-primary/10 px-4 py-2">
    <span class="text-xs font-semibold text-primary">
      Editing: {app.editing.column}
    </span>
    <Input
      bind:ref={inputEl}
      id="cell-editor"
      type="text"
      class="h-8 w-[300px] border-primary text-[13px]"
      value={app.editing.value}
      oninput={(e: Event) => {
        if (app.editing) {
          app.editing.value = (e.target as HTMLInputElement).value;
        }
      }}
      onkeydown={handleKeydown}
    />
    <Button size="sm" onclick={commitEdit}>Save</Button>
    <Button variant="outline" size="sm" onclick={cancelEdit}>Cancel</Button>
  </div>
{/if}
