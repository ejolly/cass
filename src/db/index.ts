/**
 * Database module — public API re-exports.
 */
export { createDb, getDb, closeDb, dbPath } from "./connection.ts";
export { up, down } from "./migrations/001_initial.ts";
export {
  TABLE_CAPABILITIES,
  CANVAS_PUSHABLE,
  EXCLUDED_TABLES,
  EXPORTABLE_TABLES,
  isEditable,
  isPushable,
  isPullGuarded,
  getEditableColumns,
} from "./catalog.ts";
export type { ViewerTableName, TableCapability } from "./catalog.ts";
export {
  queryStudents,
  queryAssignments,
  querySubmissions,
  queryGradebook,
  queryDataset,
} from "./queries.ts";
export type { Dataset, QueryOptions } from "./queries.ts";
export { updateCell, rawQuery, getAllRows, getTableColumns } from "./introspection.ts";
export {
  snapshotGradesSynced,
  snapshotAssignmentsSynced,
  getPendingGradeChanges,
  getPendingAssignmentChanges,
  revertGrades,
  revertAssignments,
} from "./sync.ts";
export type {
  Database,
  TableName,
  Student,
  Assignment,
  CanvasAssignment,
  CanvasSubmission,
  GHStudent,
  GHAssignment,
  GHSubmission,
  NewStudent,
  NewAssignment,
  NewCanvasAssignment,
  NewCanvasSubmission,
  NewGHStudent,
  NewGHAssignment,
  NewGHSubmission,
  StudentUpdate,
  CanvasAssignmentUpdate,
  CanvasSubmissionUpdate,
  GHStudentUpdate,
} from "./schema.ts";
