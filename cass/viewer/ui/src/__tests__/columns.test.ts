import { describe, it, expect } from "vitest";
import { getDisplayedColumns, estimateColumnWidth } from "$lib/columns.js";

describe("getDisplayedColumns", () => {
  it("hides canvas_id for canvas_assignments", () => {
    const cols = getDisplayedColumns("canvas_assignments", [
      "canvas_id",
      "name",
      "points_possible",
      "due_at",
    ]);
    expect(cols).not.toContain("canvas_id");
    expect(cols).toContain("name");
  });

  it("hides user/assignment IDs for canvas_submissions", () => {
    const cols = getDisplayedColumns("canvas_submissions", [
      "canvas_user_id",
      "canvas_assignment_id",
      "student_name",
      "score",
    ]);
    expect(cols).not.toContain("canvas_user_id");
    expect(cols).not.toContain("canvas_assignment_id");
    expect(cols).toContain("student_name");
  });

  it("applies custom column ordering for canvas_assignments", () => {
    const cols = getDisplayedColumns("canvas_assignments", [
      "name",
      "assignment_group",
      "points_possible",
      "due_at",
      "published",
      "fetched_at",
    ]);
    // assignment_group should come first per ordering config
    expect(cols[0]).toBe("assignment_group");
    expect(cols[1]).toBe("name");
    // fetched_at not in ordering, appended at end
    expect(cols[cols.length - 1]).toBe("fetched_at");
  });

  it("returns all columns for unknown tables", () => {
    const input = ["col_a", "col_b", "col_c"];
    const cols = getDisplayedColumns("some_table", input);
    expect(cols).toEqual(input);
  });

  it("handles empty column list", () => {
    expect(getDisplayedColumns("canvas_assignments", [])).toEqual([]);
  });

  it("preserves ordering for canvas_grades", () => {
    const cols = getDisplayedColumns("canvas_grades", [
      "canvas_user_id",
      "canvas_assignment_id",
      "student_name",
      "assignment_name",
      "assignment_group",
      "score",
      "posted_grade",
      "updated_at",
    ]);
    expect(cols[0]).toBe("student_name");
    expect(cols[1]).toBe("assignment_name");
    expect(cols).not.toContain("canvas_user_id");
  });
});

describe("estimateColumnWidth", () => {
  it("returns at least 90px", () => {
    expect(estimateColumnWidth("id", "INTEGER")).toBeGreaterThanOrEqual(90);
  });

  it("gives wider columns to timestamps", () => {
    const tsWidth = estimateColumnWidth("created_at", "TIMESTAMP");
    const varWidth = estimateColumnWidth("created_at", "VARCHAR");
    expect(tsWidth).toBeGreaterThanOrEqual(180);
    expect(tsWidth).toBeGreaterThanOrEqual(varWidth);
  });

  it("scales with column name length", () => {
    const short = estimateColumnWidth("id", "VARCHAR");
    const long = estimateColumnWidth("assignment_group_name", "VARCHAR");
    expect(long).toBeGreaterThan(short);
  });
});
