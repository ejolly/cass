<script lang="ts">
  import {
    type ColumnDef,
    type SortingState,
    getCoreRowModel,
    getSortedRowModel,
  } from "@tanstack/table-core";
  import { createSvelteTable, FlexRender } from "$lib/components/ui/data-table/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { app } from "$lib/state.svelte.js";
  import { classifyTable, type Row } from "$lib/types.js";
  import { getDisplayedColumns, estimateColumnWidth } from "$lib/columns.js";
  import { cn } from "$lib/utils.js";

  let sorting = $state<SortingState>([]);

  const displayedCols = $derived(
    app.selectedTable
      ? getDisplayedColumns(app.selectedTable, app.columnNames)
      : app.columnNames
  );

  /** Build a map from column name to its DuckDB type. */
  const colTypeMap = $derived(
    Object.fromEntries(
      app.columnNames.map((name, i) => [name, app.columnTypes[i] ?? "VARCHAR"])
    )
  );

  /** TanStack column definitions, built from current table metadata. */
  const columns: ColumnDef<Row>[] = $derived(
    displayedCols.map((colName) => {
      const isPK = app.schema?.primary_keys.includes(colName) ?? false;
      return {
        accessorFn: (row: Row) => row[colName] ?? "",
        id: colName,
        header: isPK ? `${colName} (PK)` : colName,
        meta: { colType: colTypeMap[colName] ?? "VARCHAR" },
      } satisfies ColumnDef<Row>;
    })
  );

  const table = createSvelteTable({
    get data() { return app.rows; },
    get columns() { return columns; },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: (updater) => {
      sorting = typeof updater === "function" ? updater(sorting) : updater;
    },
    state: {
      get sorting() { return sorting; },
    },
  });

  /** Check if the current table + schema allows editing. */
  const effectiveEditable = $derived(
    app.schema?.editable && app.selectedTable
      ? classifyTable(app.selectedTable) !== "combined"
      : false
  );

  /** Handle cell double-click for editing. */
  function handleCellDblClick(colName: string, row: Row) {
    if (!effectiveEditable || !app.schema) return;

    const realCols = app.schema.columns.map((c) => c.name);
    const isPK = app.schema.primary_keys.includes(colName);
    const isRealCol = realCols.includes(colName);

    if (isPK || !isRealCol) return;

    // Build PK values from the row
    const pk: Record<string, string> = {};
    for (const pkCol of app.schema.primary_keys) {
      pk[pkCol] = row[pkCol] ?? "";
    }

    app.editing = {
      column: colName,
      value: row[colName] ?? "",
      originalValue: row[colName] ?? "",
      pk,
    };
  }

  /** Is this row an unpublished assignment? (dim it) */
  function isUnpublished(row: Row): boolean {
    return app.selectedTable === "canvas_assignments" && row["published"] === "No";
  }
</script>

{#if app.error}
  <div class="flex flex-1 items-center justify-center text-destructive">
    {app.error}
  </div>
{:else if !app.selectedTable}
  <div class="flex flex-1 flex-col items-center justify-center gap-2">
    <p class="text-sm text-muted-foreground">Select a table from the sidebar</p>
    <p class="text-xs text-muted-foreground/60">Use &#8984;K to search within a table</p>
  </div>
{:else}
  <div class="flex-1 overflow-auto">
    <Table.Root>
      <Table.Header class="sticky top-0 z-10 bg-muted">
        {#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
          <Table.Row>
            {#each headerGroup.headers as header (header.id)}
              <Table.Head
                class={cn(
                  "cursor-pointer select-none whitespace-nowrap px-2.5 py-1.5 text-xs font-semibold",
                  header.column.getIsSorted() && "text-primary"
                )}
                style="min-width: {estimateColumnWidth(header.id, colTypeMap[header.id] ?? 'VARCHAR')}px"
                onclick={header.column.getToggleSortingHandler()}
              >
                <FlexRender content={header.column.columnDef.header} context={header.getContext()} />
                {#if header.column.getIsSorted() === "asc"} &#9650;
                {:else if header.column.getIsSorted() === "desc"} &#9660;
                {/if}
              </Table.Head>
            {/each}
          </Table.Row>
        {/each}
      </Table.Header>
      <Table.Body>
        {#each table.getRowModel().rows as row (row.id)}
          <Table.Row class={cn(isUnpublished(row.original) && "opacity-45")}>
            {#each row.getVisibleCells() as cell (cell.id)}
              <Table.Cell
                class={cn(
                  "whitespace-nowrap px-2.5 py-1 text-[13px]",
                  effectiveEditable && "cursor-pointer"
                )}
                ondblclick={() => handleCellDblClick(cell.column.id, row.original)}
              >
                <FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
              </Table.Cell>
            {/each}
          </Table.Row>
        {:else}
          <Table.Row>
            <Table.Cell colspan={columns.length} class="h-24 text-center text-muted-foreground">
              No results.
            </Table.Cell>
          </Table.Row>
        {/each}
      </Table.Body>
    </Table.Root>
  </div>
{/if}
