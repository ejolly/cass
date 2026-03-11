/**
 * GitHub Classroom operations — assignment/student fetch, DB conversion.
 */
import type { NewGHAssignment, NewGHStudent } from "@/db/schema.ts";
import { ghApiList } from "./client.ts";
import { GHAssignmentResponse, GHRosterEntry, GHStudentInfo } from "./schema.ts";

/** Fetch all assignments for a classroom. */
export async function fetchAssignments(ghId: number): Promise<GHAssignmentResponse[]> {
  return ghApiList(`/classrooms/${ghId}/assignments`, GHAssignmentResponse);
}

/** Fetch roster from all assignments' grades endpoints (deduplicated). */
export async function fetchAllStudents(ghId: number): Promise<GHStudentInfo[]> {
  const assignments = await fetchAssignments(ghId);
  const seen = new Set<string>();
  const students: GHStudentInfo[] = [];

  for (const a of assignments) {
    const entries = await ghApiList(`/assignments/${a.id}/grades`, GHRosterEntry);
    for (const e of entries) {
      const key = e.github_username.toLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        students.push(
          GHStudentInfo.parse({
            login: e.github_username,
            id: "",
            name: e.roster_identifier,
          }),
        );
      }
    }
  }

  return students;
}

/** Build a map of github_username (lowered) -> repo_full_name for an assignment. */
export async function buildRepoMap(assignmentId: number): Promise<Map<string, string>> {
  const entries = await ghApiList(`/assignments/${assignmentId}/grades`, GHRosterEntry);
  const map = new Map<string, string>();
  for (const e of entries) {
    if (e.student_repository_name) {
      // grades endpoint gives repo name, construct full_name from URL
      const urlMatch = /github\.com\/([^/]+\/[^/]+)/.exec(e.student_repository_url);
      if (urlMatch?.[1] != null) {
        map.set(e.github_username.toLowerCase(), urlMatch[1]);
      }
    }
  }
  return map;
}

/** Resolve the gh_id for an assignment by its slug. */
export async function resolveAssignmentId(ghId: number, slug: string): Promise<number> {
  const assignments = await fetchAssignments(ghId);
  const match = assignments.find((a) => a.slug === slug);
  if (!match) throw new Error(`Assignment "${slug}" not found in classroom ${ghId}`);
  return match.id;
}

/** Convert GH assignment responses to DB rows. */
export function assignmentsToDB(assignments: GHAssignmentResponse[]): NewGHAssignment[] {
  return assignments.map((a) => ({
    slug: a.slug,
    gh_id: a.id,
    title: a.title,
    deadline: a.deadline,
    points_possible: 1.0,
    accepted: a.accepted,
    submissions_count: a.submissions,
    passing_count: a.passing,
    starter_code_repo: a.starter_code_repository?.full_name ?? "",
    submittable_files: "",
  }));
}

/** Convert GH student info to DB rows. */
export function studentsToDB(students: GHStudentInfo[]): NewGHStudent[] {
  return students.map((s) => ({
    github_username: s.login,
    github_id: Number(s.id) || 0,
    name: s.name,
    email: s.email,
    excluded: 0,
  }));
}
