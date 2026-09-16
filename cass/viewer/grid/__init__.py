"""AG Grid UI layer — column defs, edit handlers, pending cell tracking, utilities."""

from __future__ import annotations

__docformat__ = "google"

from .columns import (
    build_column_defs,
    build_gradebook_view,
    get_display_columns,
    get_table_rows,
    row_id_js,
    sanitize,
)
from .handlers import (
    attach_checkbox_toggle,
    attach_date_autocommit,
    attach_edit_handler,
    attach_gradebook_edit_handler,
)
from .pending import (
    clear_pending_cells,
    restore_pending_cells,
)
from .utils import (
    _grid_to_markdown as _grid_to_markdown,  # pyright: ignore[reportPrivateUsage]
)
from .utils import (
    apply_search,
    export_csv,
    export_markdown,
    find_grid,
    notify,
    reload_current_grid,
    revert_pending,
)

__all__ = [
    "_grid_to_markdown",
    "apply_search",
    "attach_checkbox_toggle",
    "attach_date_autocommit",
    "attach_edit_handler",
    "attach_gradebook_edit_handler",
    "build_column_defs",
    "build_gradebook_view",
    "clear_pending_cells",
    "export_csv",
    "export_markdown",
    "find_grid",
    "get_display_columns",
    "get_table_rows",
    "notify",
    "reload_current_grid",
    "restore_pending_cells",
    "revert_pending",
    "row_id_js",
    "sanitize",
]
