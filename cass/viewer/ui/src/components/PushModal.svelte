<script lang="ts">
  import { app, setStatus } from "$lib/state.svelte.js";
  import * as api from "$lib/api.js";
  import type { PreviewData } from "$lib/types.js";

  const isOpen = $derived(app.modal.kind !== "closed");

  $effect(() => {
    if (app.modal.kind === "loading") fetchPreview();
  });

  async function fetchPreview() {
    try {
      const preview = await api.fetchCanvasPreview();
      app.modal = { kind: "preview", data: preview };
    } catch (e) {
      app.modal = { kind: "error", message: e instanceof Error ? e.message : String(e) };
    }
  }

  async function applyPush() {
    if (app.modal.kind !== "preview") return;
    const preview = app.modal.data;
    app.modal = { kind: "pushing", data: preview };

    try {
      const result = await api.applyCanvasPush();
      if (result.ok) {
        app.modal = { kind: "closed" };
        app.pendingCount = 0;
        setStatus("Pushed to Canvas", "success", 6000);
        if (app.selectedTable) {
          const { schema, data } = await api.fetchSchemaAndData(app.selectedTable);
          app.schema = schema;
          app.columnNames = data.columns;
          app.columnTypes = data.types;
          const rows = api.parseRows(data);
          app.allRows = rows;
          app.rows = app.searchText
            ? rows.filter((r) => api.matchesSearch(app.searchText, r))
            : rows;
        }
      } else {
        app.modal = { kind: "results", results: result.results };
        try {
          const pending = await api.fetchPending();
          app.pendingCount = pending.count;
        } catch { /* ignore */ }
      }
    } catch {
      app.modal = { kind: "closed" };
      setStatus("Push failed", "error", 6000);
    }
  }

  function close() {
    app.modal = { kind: "closed" };
  }

  function previewData(): PreviewData | null {
    if (app.modal.kind === "preview" || app.modal.kind === "pushing") return app.modal.data;
    return null;
  }

  function pushableCount(data: PreviewData): number {
    return data.changes.filter((c) => !c.error).length;
  }
</script>

<div class="modal" class:modal-open={isOpen}>
  <div class="modal-box max-w-xl">
    <button class="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onclick={close}>
      &#10005;
    </button>
    <h3 class="text-lg font-bold">Push to Canvas</h3>

    <div class="py-4">
      {#if app.modal.kind === "loading"}
        <p class="text-center opacity-50">Comparing with Canvas...</p>

      {:else if app.modal.kind === "error"}
        <p class="text-error">{app.modal.message}</p>

      {:else if app.modal.kind === "results"}
        {@const succeeded = app.modal.results.filter((r) => r.ok)}
        {@const failed = app.modal.results.filter((r) => !r.ok)}
        <p class="font-semibold">{succeeded.length} pushed, {failed.length} failed:</p>
        <div class="mt-2 space-y-1">
          {#each app.modal.results as r}
            {#if r.ok}
              <p class="text-success">&#10003; Assignment {r.canvas_id ?? "?"}</p>
            {:else}
              <p class="text-error">&#10007; Assignment {r.canvas_id ?? "?"}: {r.error ?? "Unknown"}</p>
            {/if}
          {/each}
        </div>

      {:else if previewData()}
        {@const data = previewData()!}
        {@const assignmentChanges = data.changes.filter((c) => c.table === "canvas_assignments")}
        {@const gradeChanges = data.changes.filter((c) => c.table === "canvas_grades")}

        {#if data.changes.length === 0}
          <p class="text-center opacity-50">No pending changes</p>
        {:else}
          {#if assignmentChanges.length > 0}
            <h4 class="mb-1 font-semibold">Assignment changes</h4>
            <table class="table table-xs">
              <thead>
                <tr><th>Assignment</th><th>Field</th><th>On Canvas</th><th>New value</th></tr>
              </thead>
              <tbody>
                {#each assignmentChanges as ch}
                  <tr class={ch.conflict ? "bg-warning/10" : ""}>
                    {#if ch.error}
                      <td colspan="4" class="text-error">{ch.name}: {ch.error}</td>
                    {:else}
                      <td>{ch.name}</td>
                      <td>
                        {ch.column}
                        {#if ch.conflict}<span class="text-warning"> &#9888;</span>{/if}
                      </td>
                      <td class="opacity-50">{ch.live ?? "null"}</td>
                      <td class="font-semibold">{ch.current ?? "null"}</td>
                    {/if}
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}

          {#if gradeChanges.length > 0}
            <h4 class="mb-1 mt-4 font-semibold">Grade changes</h4>
            <table class="table table-xs">
              <thead>
                <tr><th>Student — Assignment</th><th>On Canvas</th><th>New grade</th></tr>
              </thead>
              <tbody>
                {#each gradeChanges as ch}
                  <tr class={ch.conflict ? "bg-warning/10" : ""}>
                    {#if ch.error}
                      <td colspan="3" class="text-error">{ch.name}: {ch.error}</td>
                    {:else}
                      <td>
                        {ch.name}
                        {#if ch.conflict}<span class="text-warning"> &#9888;</span>{/if}
                      </td>
                      <td class="opacity-50">{ch.live ?? "null"}</td>
                      <td class="font-semibold">{ch.current ?? "null"}</td>
                    {/if}
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}

          {#if data.has_conflicts}
            <div class="alert alert-warning mt-4 text-sm">
              Some Canvas values differ from when you last pulled. Pushing will overwrite.
            </div>
          {/if}
        {/if}
      {/if}
    </div>

    <div class="modal-action">
      <button class="btn btn-ghost" onclick={close}>
        {app.modal.kind === "results" ? "Close" : "Cancel"}
      </button>

      {#if app.modal.kind === "preview" && pushableCount(app.modal.data) > 0}
        {@const count = pushableCount(app.modal.data)}
        <button class="btn btn-primary" onclick={applyPush}>
          Push {count} change{count === 1 ? "" : "s"}
        </button>
      {/if}

      {#if app.modal.kind === "pushing"}
        <button class="btn btn-primary" disabled>
          <span class="loading loading-spinner loading-xs"></span>
          Pushing...
        </button>
      {/if}
    </div>
  </div>
  <button class="modal-backdrop" onclick={close} aria-label="Close"></button>
</div>
