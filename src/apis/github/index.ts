/**
 * GitHub API module — public API re-exports.
 */
export { checkAvailable, checkAuth, ghApi, ghApiList, ghApiSingle, ghApiExists } from "./client.ts";
export {
  fetchAssignments,
  fetchAllStudents,
  buildRepoMap,
  resolveAssignmentId,
  assignmentsToDB,
  studentsToDB,
} from "./classroom.ts";
export { sanitizeStudentDir, pullRepos } from "./fetch.ts";
export type { PullGHOptions, PullGHCounts } from "./fetch.ts";
