/**
 * Actions module — public API re-exports.
 */
export {
  getConfig,
  loadConfig,
  resetConfig,
  configFilePath,
  updateConfig,
  hasCanvas,
  hasClassroom,
  hasClassroomUrl,
  classroomNeedsResolution,
  classroomStatus,
  parseCanvasCourseUrl,
  parseClassroomUrl,
  findProjectRoot,
} from "./config.ts";
export type {
  Config,
  ConfigState,
  ConfigUpdate,
  CanvasModuleSpec,
  CanvasAssignmentSpec,
} from "./config.ts";
export { checkPrerequisites } from "./doctor.ts";
export type { Check, CheckStatus } from "./doctor.ts";
export { matchStudents, findCandidates, normalize, slugify, slugMatch } from "./matching.ts";
export type { MatchResult } from "./matching.ts";
export { pullAll, pullStudents, pullAssignments, pullSubmissions } from "./pull.ts";
export type { PullMode } from "./pull.ts";
