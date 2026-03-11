/**
 * Student matching — name normalization and slug matching.
 */
import type { CanvasStudentResponse } from "@/apis/canvas/schema.ts";
import type { GHStudentInfo } from "@/apis/github/schema.ts";

/** Normalize a name for matching: lowercase, handle "Last, First", strip non-alpha, sort tokens. */
export function normalize(name: string): string {
  const lower = name.toLowerCase();
  // Handle "Last, First" format → "First Last"
  const oriented = lower.includes(",")
    ? lower
        .split(",")
        .map((p) => p.trim())
        .reverse()
        .join(" ")
    : lower;
  // Replace non-alpha (except spaces) with spaces, split into tokens, sort
  return oriented
    .replace(/[^a-z\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .sort()
    .join(" ");
}

export interface MatchResult {
  matched: Map<string, number>; // gh_login -> canvas_id
  unmatchedGH: GHStudentInfo[];
  unmatchedCanvas: CanvasStudentResponse[];
}

/** Match GH students to Canvas students by normalized name. */
export function matchStudents(
  ghStudents: GHStudentInfo[],
  canvasStudents: CanvasStudentResponse[],
): MatchResult {
  const matched = new Map<string, number>();
  const unmatchedGH: GHStudentInfo[] = [];
  const matchedCanvasIds = new Set<number>();

  // Build canvas lookup by normalized name
  const canvasByName = new Map<string, CanvasStudentResponse>();
  for (const cs of canvasStudents) {
    canvasByName.set(normalize(cs.name), cs);
  }

  // Pass 1: exact normalized name match
  for (const gh of ghStudents) {
    const key = normalize(gh.name);
    const canvas = canvasByName.get(key);
    if (canvas && !matchedCanvasIds.has(canvas.id)) {
      matched.set(gh.login, canvas.id);
      matchedCanvasIds.add(canvas.id);
    } else {
      unmatchedGH.push(gh);
    }
  }

  const unmatchedCanvas = canvasStudents.filter((cs) => !matchedCanvasIds.has(cs.id));

  return { matched, unmatchedGH, unmatchedCanvas };
}

/** Find candidate Canvas matches for a GH student, ranked by token overlap. */
export function findCandidates(
  ghStudent: GHStudentInfo,
  canvasPool: CanvasStudentResponse[],
): CanvasStudentResponse[] {
  const ghTokens = normalize(ghStudent.name).split(" ");
  if (ghTokens.length === 0) return [];

  const scored = canvasPool
    .map((cs) => {
      const csTokens = normalize(cs.name).split(" ");
      const overlap = ghTokens.filter((t) => csTokens.includes(t)).length;
      return { cs, overlap };
    })
    .filter((s) => s.overlap >= Math.min(2, ghTokens.length) && s.overlap > 0)
    .sort((a, b) => b.overlap - a.overlap);

  return scored.map((s) => s.cs);
}

/** Convert a name/title to a URL-friendly slug. */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[_/()→\-\s]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Check if two slugs match by token overlap. */
export function slugMatch(ghSlug: string, canvasSlug: string): boolean {
  const ghTokens = ghSlug.split("-").filter(Boolean);
  const canvasTokens = canvasSlug.split("-").filter(Boolean);
  const overlap = ghTokens.filter((t) => canvasTokens.includes(t)).length;
  return overlap >= Math.min(ghTokens.length, canvasTokens.length) && overlap > 0;
}
