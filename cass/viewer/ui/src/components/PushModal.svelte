<script lang="ts">
  import { app, setStatus } from "$lib/state.svelte.js";
  import * as api from "$lib/api.js";
  import type { PreviewData } from "$lib/types.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { cn } from "$lib/utils.js";

  const isOpen = $derived(app.modal.kind !== "closed");

  // Trigger preview fetch when modal opens to loading state
  $effect(() => {
    if (app.modal.kind === "loading") {
      fetchPreview();
    }
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
        // Refresh current table
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
        // Refresh pending count
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

  function closeModal() {
    app.modal = { kind: "closed" };
  }

  function onOpenChange(open: boolean) {
    if (!open) closeModal();
  }

  // Helpers for preview data
  function previewData(): PreviewData | null {
    if (app.modal.kind === "preview" || app.modal.kind === "pushing") {
      return app.modal.data;
    }
    return null;
  }

  function pushableCount(data: PreviewData): number {
    return data.changes.filter((c) => !c.error).length;
  }
</script>

<Dialog.Root open={isOpen} {onOpenChange}>
  <Dialog.Content class="max-h-[600px] max-w-[640px] overflow-hidden flex flex-col">
    <Dialog.Header>
      <Dialog.Title>Push to Canvas</Dialog.Title>
    </Dialog.Header>

    <!-- Body -->
    <div class="min-h-[100px] flex-1 overflow-y-auto px-6 py-4">
      {#if app.modal.kind === "loading"}
        <p class="text-center text-muted-foreground">Comparing with Canvas...</p>

      {:else if app.modal.kind === "error"}
        <p class="text-destructive">{app.modal.message}</p>

      {:else if app.modal.kind === "results"}
        {@const succeeded = app.modal.results.filter((r) => r.ok)}
        {@const failed = app.modal.results.filter((r) => !r.ok)}
        <p class="font-semibold">{succeeded.length} pushed, {failed.length} failed:</p>
        <div class="mt-2 space-y-1">
          {#each app.modal.results as r}
            {#if r.ok}
              <p class="text-green-600">&#10003; Assignment {r.canvas_id ?? "?"}</p>
            {:else}
              <p class="text-destructive">&#10007; Assignment {r.canvas_id ?? "?"}: {r.error ?? "Unknown error"}</p>
            {/if}
          {/each}
        </div>

      {:else if previewData()}
        {@const data = previewData()!}
        {@const assignmentChanges = data.changes.filter((c) => c.table === "canvas_assignments")}
        {@const gradeChanges = data.changes.filter((c) => c.table === "canvas_grades")}

        {#if data.changes.length === 0}
          <p class="text-center text-muted-foreground">No pending changes</p>
        {:else}
          <div class="space-y-4">
            {#if assignmentChanges.length > 0}
              <div>
                <h3 class="mb-2 font-semibold">Assignment changes</h3>
                <table class="w-full text-[13px]">
                  <thead>
                    <tr class="border-b-2 text-left">
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">Assignment</th>
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">Field</th>
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">On Canvas</th>
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">New value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each assignmentChanges as ch}
                      <tr class={cn("border-b", ch.conflict && "bg-destructive/10")}>
                        {#if ch.error}
                          <td colspan="4" class="px-2 py-1 text-destructive">{ch.name}: {ch.error}</td>
                        {:else}
                          <td class="px-2 py-1">{ch.name}</td>
                          <td class="px-2 py-1">
                            {ch.column}
                            {#if ch.conflict}<span class="text-destructive"> &#9888;</span>{/if}
                          </td>
                          <td class="px-2 py-1 text-muted-foreground">{ch.live ?? "null"}</td>
                          <td class="px-2 py-1 font-semibold">{ch.current ?? "null"}</td>
                        {/if}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}

            {#if gradeChanges.length > 0}
              <div>
                <h3 class="mb-2 font-semibold">Grade changes</h3>
                <table class="w-full text-[13px]">
                  <thead>
                    <tr class="border-b-2 text-left">
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">Student — Assignment</th>
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">On Canvas</th>
                      <th class="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">New grade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each gradeChanges as ch}
                      <tr class={cn("border-b", ch.conflict && "bg-destructive/10")}>
                        {#if ch.error}
                          <td colspan="3" class="px-2 py-1 text-destructive">{ch.name}: {ch.error}</td>
                        {:else}
                          <td class="px-2 py-1">
                            {ch.name}
                            {#if ch.conflict}<span class="text-destructive"> &#9888;</span>{/if}
                          </td>
                          <td class="px-2 py-1 text-muted-foreground">{ch.live ?? "null"}</td>
                          <td class="px-2 py-1 font-semibold">{ch.current ?? "null"}</td>
                        {/if}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}

            {#if data.has_conflicts}
              <div class="rounded-md border border-destructive/25 bg-destructive/5 p-3 text-xs text-destructive">
                Some Canvas values differ from when you last pulled. Pushing will overwrite the current Canvas values.
              </div>
            {/if}
          </div>
        {/if}
      {/if}
    </div>

    <!-- Footer -->
    <Dialog.Footer class="border-t px-6 py-3">
      <Button variant="outline" onclick={closeModal}>
        {app.modal.kind === "results" ? "Close" : "Cancel"}
      </Button>

      {#if app.modal.kind === "preview" && pushableCount(app.modal.data) > 0}
        {@const count = pushableCount(app.modal.data)}
        <Button onclick={applyPush}>
          Push {count} change{count === 1 ? "" : "s"}
        </Button>
      {/if}

      {#if app.modal.kind === "pushing"}
        <Button disabled>Pushing...</Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
