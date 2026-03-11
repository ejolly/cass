import { describe, expect, it } from "bun:test";
import {
	findCandidates,
	matchStudents,
	normalize,
	slugMatch,
	slugify,
} from "../../src/actions/matching.ts";
import type { CanvasStudentResponse } from "../../src/apis/canvas/schema.ts";
import type { GHStudentInfo } from "../../src/apis/github/schema.ts";

describe("matching", () => {
	describe("normalize", () => {
		it("lowercases and sorts tokens", () => {
			expect(normalize("Alice Smith")).toBe("alice smith");
		});

		it("handles Last, First format", () => {
			expect(normalize("Smith, Alice")).toBe("alice smith");
		});

		it("strips non-alpha chars as word separators", () => {
			expect(normalize("O'Brien Jr.")).toBe("brien jr o");
		});
	});

	describe("matchStudents", () => {
		const ghStudents: GHStudentInfo[] = [
			{ login: "alice-gh", id: "1", name: "Alice Smith", email: "" },
			{ login: "bob-gh", id: "2", name: "Bob Jones", email: "" },
			{ login: "charlie-gh", id: "3", name: "Unknown Person", email: "" },
		];

		const canvasStudents: CanvasStudentResponse[] = [
			{
				id: 100,
				name: "Smith, Alice",
				sortable_name: "Smith, Alice",
				email: null,
				sis_user_id: null,
				login_id: null,
			},
			{
				id: 200,
				name: "Bob Jones",
				sortable_name: "Jones, Bob",
				email: null,
				sis_user_id: null,
				login_id: null,
			},
			{
				id: 300,
				name: "Extra Student",
				sortable_name: "Student, Extra",
				email: null,
				sis_user_id: null,
				login_id: null,
			},
		];

		it("matches by normalized name", () => {
			const result = matchStudents(ghStudents, canvasStudents);
			expect(result.matched.get("alice-gh")).toBe(100);
			expect(result.matched.get("bob-gh")).toBe(200);
		});

		it("reports unmatched students", () => {
			const result = matchStudents(ghStudents, canvasStudents);
			expect(result.unmatchedGH).toHaveLength(1);
			expect(result.unmatchedGH[0]!.login).toBe("charlie-gh");
			expect(result.unmatchedCanvas).toHaveLength(1);
			expect(result.unmatchedCanvas[0]!.id).toBe(300);
		});
	});

	describe("findCandidates", () => {
		it("returns candidates ranked by token overlap", () => {
			const gh: GHStudentInfo = {
				login: "alice",
				id: "1",
				name: "Alice Smith",
				email: "",
			};
			const pool: CanvasStudentResponse[] = [
				{
					id: 1,
					name: "Alice Smith-Jones",
					sortable_name: "",
					email: null,
					sis_user_id: null,
					login_id: null,
				},
				{
					id: 2,
					name: "Bob Jones",
					sortable_name: "",
					email: null,
					sis_user_id: null,
					login_id: null,
				},
			];
			const candidates = findCandidates(gh, pool);
			// Alice Smith matches "Alice Smith-Jones" (2 token overlap)
			expect(candidates.length).toBe(1);
			expect(candidates[0]!.id).toBe(1);
		});
	});

	describe("slugify", () => {
		it("converts to kebab-case", () => {
			expect(slugify("Homework 1")).toBe("homework-1");
			expect(slugify("Lab (Week 3)")).toBe("lab-week-3");
		});

		it("collapses multiple hyphens", () => {
			expect(slugify("foo  --  bar")).toBe("foo-bar");
		});
	});

	describe("slugMatch", () => {
		it("matches identical slugs", () => {
			expect(slugMatch("hw1", "hw1")).toBe(true);
		});

		it("matches by token overlap", () => {
			expect(slugMatch("homework-1", "homework-1-intro")).toBe(true);
		});

		it("rejects non-overlapping slugs", () => {
			expect(slugMatch("hw1", "lab2")).toBe(false);
		});
	});
});
