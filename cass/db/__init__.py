"""Database layer — schema, CRUD, introspection, and enriched queries.

Import everything from here::

    from cass.db import get_db, CanvasStudent, save_canvas_students
    from cass import db  # also works
"""

from __future__ import annotations

__docformat__ = "google"

from .catalog import (
    CANVAS_PUSHABLE,
    CANVAS_WORKING_TABLES,
    EXPORTABLE_TABLES,
    IMPORT_SIGNATURES,
    PULL_GUARDED_TABLES,
    TABLE_CAPABILITIES,
    TableCapability,
    get_table_capability,
)
from .core import (
    DB_FILENAME,
    EXCLUDED_TABLES,
    READ_ONLY_TABLES,
    connect_db,
    db_path,
    editable_canvas_tables,
    get_assignment_groups,
    get_db,
    get_meta,
    init_schema,
    load_canvas_assignment_ids,
    load_canvas_grades,
    load_canvas_student_ids,
    open_db,
    reset,
    save_canvas_assignments,
    save_canvas_grades,
    save_canvas_students,
    save_canvas_submissions,
    save_meta,
    upsert_canvas_grade,
)
from .core import _db as _db
from .introspection import (
    get_column_names,
    get_primary_keys,
    get_tables,
    is_editable,
    revert_changes,
    update_cell,
)
from .queries import (
    ENRICHED_QUERIES,
    QUERY_DATASETS,
    TABLE_QUERY_DATASETS,
    QueryResult,
    build_submissions_query,
    get_enriched_rows,
    run_query,
    sql,
)
from .schema import (
    CanvasAssignment,
    CanvasGrade,
    CanvasStudent,
    CanvasSubmission,
)
from .sync import (
    canvas_apply,
    canvas_preview,
    get_pending_changes,
    get_pull_blocking_tables,
    mark_synced_assignments,
    mark_synced_grades,
    preview_assignments,
    preview_grades,
    pull_block_reason,
    snapshot_canvas_synced,
)
from .views import (
    CanvasGradebookAssignment,
    CanvasGradebookData,
    CanvasGradebookStudent,
    build_canvas_gradebook_matrix,
    load_canvas_gradebook_data,
)

__all__ = [
    "CANVAS_PUSHABLE",
    "CANVAS_WORKING_TABLES",
    "DB_FILENAME",
    "ENRICHED_QUERIES",
    "EXCLUDED_TABLES",
    "EXPORTABLE_TABLES",
    "IMPORT_SIGNATURES",
    "PULL_GUARDED_TABLES",
    "QUERY_DATASETS",
    "READ_ONLY_TABLES",
    "TABLE_CAPABILITIES",
    "TABLE_QUERY_DATASETS",
    "CanvasAssignment",
    "CanvasGrade",
    "CanvasGradebookAssignment",
    "CanvasGradebookData",
    "CanvasGradebookStudent",
    "CanvasStudent",
    "CanvasSubmission",
    "QueryResult",
    "TableCapability",
    "build_canvas_gradebook_matrix",
    "build_submissions_query",
    "canvas_apply",
    "canvas_preview",
    "connect_db",
    "db_path",
    "editable_canvas_tables",
    "get_assignment_groups",
    "get_column_names",
    "get_db",
    "get_enriched_rows",
    "get_meta",
    "get_pending_changes",
    "get_primary_keys",
    "get_pull_blocking_tables",
    "get_table_capability",
    "get_tables",
    "init_schema",
    "is_editable",
    "load_canvas_assignment_ids",
    "load_canvas_gradebook_data",
    "load_canvas_grades",
    "load_canvas_student_ids",
    "mark_synced_assignments",
    "mark_synced_grades",
    "open_db",
    "preview_assignments",
    "preview_grades",
    "pull_block_reason",
    "reset",
    "revert_changes",
    "run_query",
    "save_canvas_assignments",
    "save_canvas_grades",
    "save_canvas_students",
    "save_canvas_submissions",
    "save_meta",
    "snapshot_canvas_synced",
    "sql",
    "update_cell",
    "upsert_canvas_grade",
]
