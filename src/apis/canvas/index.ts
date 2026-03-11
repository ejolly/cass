/**
 * Canvas API module — public API re-exports.
 */
export {
  createCanvasClient,
  getPaginated,
  waitForProgress,
  resolveResource,
  loadCanvasToken,
} from "./client.ts";
export type { CanvasClientOptions } from "./client.ts";
export {
  fetchStudentsWithSections,
  fetchCanvasAssignments,
  fetchCanvasSubmissions,
} from "./matching.ts";
export {
  buildGradePushData,
  buildPushPreview,
  pushGrades,
  pushAssignments,
  isValidGrade,
} from "./sync.ts";
export type { GradeData, PushPreviewItem, PushResult } from "./sync.ts";
export { scoreToLetter, parseSortableName, generateEgrades } from "./egrades.ts";
export type { EgradesResult } from "./egrades.ts";
