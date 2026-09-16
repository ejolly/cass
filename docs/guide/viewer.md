# Viewer

`cass view` starts a local NiceGUI server and opens an AG Grid interface in your browser.

## Layout

- **Sidebar**: tables grouped under Canvas LMS, plus sync status and the **Push** and **Revert** controls.
- **Toolbar**: search, CSV and Markdown export, reload.
- **Grid**: the selected table. Sort by clicking headers; filter with the search box.

## Editing

Only **Gradebook** and **Assignments** are editable. Everything else is read-only.

- Double-click a cell to edit, like a spreadsheet.
- Boolean columns toggle on click. Date columns commit when you pick a date.
- Edited cells turn orange and count toward the pending badge. They survive closing the browser and restarting `cass view`.

## Pushing

Click **Push** in the sidebar to see a summary of pending changes grouped by student and assignment, then confirm. Pushed cells lose their orange highlight. **Revert** discards every pending change instead.

## Creating and deleting assignments

The Assignments table has **Create** and **Delete** actions. Both apply to Canvas immediately after confirmation and refresh the local tables.

## Exporting

**CSV** and **Markdown** each download the current table as a file. The Markdown file pastes cleanly into notes or an LLM prompt.
