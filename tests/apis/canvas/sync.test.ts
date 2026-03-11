import { describe, expect, it } from "bun:test";
import { buildGradePushData, isValidGrade } from "../../../src/apis/canvas/sync.ts";
import type { CanvasSubmission } from "../../../src/db/schema.ts";

/** Helper to create a minimal CanvasSubmission with grade data. */
function makeSub(
	userId: number,
	assignmentId: number,
	postedGrade: string,
	score: number | null = null,
): CanvasSubmission {
	return {
		canvas_user_id: userId,
		canvas_assignment_id: assignmentId,
		submitted: 1,
		submitted_at: null,
		late: 0,
		lateness_seconds: 0,
		score,
		workflow_state: "graded",
		fetched_at: 0,
		posted_grade: postedGrade,
		grade_updated_at: 0,
		_synced_posted_grade: "",
	};
}

describe("canvas sync", () => {
	describe("isValidGrade", () => {
		it("accepts normal grades", () => {
			expect(isValidGrade("10")).toBe(true);
			expect(isValidGrade("A")).toBe(true);
			expect(isValidGrade("0")).toBe(true);
		});

		it("rejects placeholder values", () => {
			expect(isValidGrade(null)).toBe(false);
			expect(isValidGrade(undefined)).toBe(false);
			expect(isValidGrade("")).toBe(false);
			expect(isValidGrade("-")).toBe(false);
			expect(isValidGrade("?")).toBe(false);
		});
	});

	describe("buildGradePushData", () => {
		it("groups grades by assignment", () => {
			const subs: CanvasSubmission[] = [
				makeSub(1, 100, "8", 8),
				makeSub(2, 100, "9", 9),
				makeSub(1, 200, "7", 7),
			];
			const [data, skipped] = buildGradePushData(subs);
			expect(skipped).toBe(0);
			expect(data["100"]).toEqual({ "1": "8", "2": "9" });
			expect(data["200"]).toEqual({ "1": "7" });
		});

		it("skips invalid grades", () => {
			const subs: CanvasSubmission[] = [
				makeSub(1, 100, "8", 8),
				makeSub(2, 100, ""),
				makeSub(3, 100, "-"),
			];
			const [data, skipped] = buildGradePushData(subs);
			expect(skipped).toBe(2);
			expect(Object.keys(data["100"]!)).toEqual(["1"]);
		});
	});
});
