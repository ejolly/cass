import { describe, expect, it } from "bun:test";
import {
	CANVAS_PUSHABLE,
	EXCLUDED_TABLES,
	EXPORTABLE_TABLES,
	TABLE_CAPABILITIES,
	getEditableColumns,
	isEditable,
	isPullGuarded,
	isPushable,
} from "../../src/db/catalog.ts";

describe("catalog", () => {
	it("has capabilities for all viewer tables", () => {
		expect(Object.keys(TABLE_CAPABILITIES)).toEqual([
			"canvas_submissions",
			"canvas_assignments",
			"gh_submissions",
			"gh_students",
			"gh_assignments",
			"students",
			"assignments",
		]);
	});

	it("marks canvas_submissions and canvas_assignments as editable and pushable", () => {
		expect(isEditable("canvas_submissions")).toBe(true);
		expect(isEditable("canvas_assignments")).toBe(true);
		expect(isPushable("canvas_submissions")).toBe(true);
		expect(isPushable("canvas_assignments")).toBe(true);
	});

	it("marks gh_students as editable but not pushable", () => {
		expect(isEditable("gh_students")).toBe(true);
		expect(isPushable("gh_students")).toBe(false);
	});

	it("marks non-editable tables correctly", () => {
		expect(isEditable("gh_submissions")).toBe(false);
		expect(isEditable("students")).toBe(false);
		expect(isEditable("gh_assignments")).toBe(false);
	});

	it("restricts canvas_submissions editable columns to posted_grade", () => {
		expect(getEditableColumns("canvas_submissions")).toEqual(["posted_grade"]);
	});

	it("restricts gh_students editable columns to excluded", () => {
		expect(getEditableColumns("gh_students")).toEqual(["excluded"]);
	});

	it("returns null for non-restricted editable tables", () => {
		expect(getEditableColumns("canvas_assignments")).toBeNull();
	});

	it("defines pushable columns for canvas tables", () => {
		expect(CANVAS_PUSHABLE.canvas_assignments).toEqual([
			"name",
			"points_possible",
			"due_at",
			"published",
		]);
		expect(CANVAS_PUSHABLE.canvas_submissions).toEqual(["posted_grade"]);
	});

	it("identifies pull-guarded tables", () => {
		expect(isPullGuarded("canvas_submissions")).toBe(true);
		expect(isPullGuarded("canvas_assignments")).toBe(true);
		expect(isPullGuarded("gh_students")).toBe(false);
	});

	it("excludes only meta from viewer", () => {
		expect(EXCLUDED_TABLES).toEqual(["meta"]);
	});

	it("exports tables in correct order", () => {
		expect(EXPORTABLE_TABLES[0]).toBe("students");
		expect(EXPORTABLE_TABLES[EXPORTABLE_TABLES.length - 1]).toBe("canvas_submissions");
	});
});
