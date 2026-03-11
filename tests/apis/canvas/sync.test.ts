import { describe, expect, it } from "bun:test";
import { buildGradePushData, isValidGrade } from "../../../src/apis/canvas/sync.ts";
import type { CanvasGrade } from "../../../src/db/schema.ts";

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
			const grades: CanvasGrade[] = [
				{
					canvas_user_id: 1,
					canvas_assignment_id: 100,
					score: 8,
					posted_grade: "8",
					updated_at: 0,
				},
				{
					canvas_user_id: 2,
					canvas_assignment_id: 100,
					score: 9,
					posted_grade: "9",
					updated_at: 0,
				},
				{
					canvas_user_id: 1,
					canvas_assignment_id: 200,
					score: 7,
					posted_grade: "7",
					updated_at: 0,
				},
			];
			const [data, skipped] = buildGradePushData(grades);
			expect(skipped).toBe(0);
			expect(data["100"]).toEqual({ "1": "8", "2": "9" });
			expect(data["200"]).toEqual({ "1": "7" });
		});

		it("skips invalid grades", () => {
			const grades: CanvasGrade[] = [
				{
					canvas_user_id: 1,
					canvas_assignment_id: 100,
					score: 8,
					posted_grade: "8",
					updated_at: 0,
				},
				{
					canvas_user_id: 2,
					canvas_assignment_id: 100,
					score: null,
					posted_grade: "",
					updated_at: 0,
				},
				{
					canvas_user_id: 3,
					canvas_assignment_id: 100,
					score: null,
					posted_grade: "-",
					updated_at: 0,
				},
			];
			const [data, skipped] = buildGradePushData(grades);
			expect(skipped).toBe(2);
			expect(Object.keys(data["100"]!)).toEqual(["1"]);
		});
	});
});
