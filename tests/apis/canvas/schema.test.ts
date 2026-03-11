import { describe, expect, it } from "bun:test";
import {
  CanvasAssignmentResponse,
  CanvasCourse,
  CanvasFile,
  CanvasProgress,
  CanvasStudentResponse,
  CanvasSubmissionResponse,
  CanvasTab,
} from "../../../src/apis/canvas/schema.ts";

describe("Canvas Zod schemas", () => {
  it("parses a course response", () => {
    const raw = {
      id: 12345,
      name: "CS 101",
      course_code: "CS101",
      workflow_state: "available",
      total_students: 45,
    };
    const course = CanvasCourse.parse(raw);
    expect(course.id).toBe(12345);
    expect(course.total_students).toBe(45);
  });

  it("parses student with defaults", () => {
    const raw = { id: 100, name: "Alice" };
    const student = CanvasStudentResponse.parse(raw);
    expect(student.sortable_name).toBe("");
    expect(student.email).toBeNull();
    expect(student.sis_user_id).toBeNull();
  });

  it("transforms CanvasFile content-type to contentType", () => {
    const raw = {
      id: 1,
      display_name: "syllabus.pdf",
      "content-type": "application/pdf",
    };
    const file = CanvasFile.parse(raw);
    expect(file.contentType).toBe("application/pdf");
    // The hyphenated key should not exist on the output
    expect("content-type" in file).toBe(false);
  });

  it("parses tab with string id", () => {
    const raw = { id: "assignments", label: "Assignments" };
    const tab = CanvasTab.parse(raw);
    expect(tab.id).toBe("assignments");
    expect(typeof tab.id).toBe("string");
  });

  it("parses assignment with all defaults", () => {
    const raw = { id: 9001, name: "HW1" };
    const a = CanvasAssignmentResponse.parse(raw);
    expect(a.published).toBe(false);
    expect(a.post_manually).toBe(false);
    expect(a.submission_types).toEqual([]);
    expect(a.due_at).toBeNull();
  });

  it("parses submission response", () => {
    const raw = {
      user_id: 100,
      submitted_at: "2026-01-15T10:00:00Z",
      late: true,
      missing: false,
      seconds_late: 3600,
      grade: "A",
      score: 95,
      workflow_state: "graded",
    };
    const sub = CanvasSubmissionResponse.parse(raw);
    expect(sub.late).toBe(true);
    expect(sub.score).toBe(95);
    expect(sub.seconds_late).toBe(3600);
  });

  it("parses progress with workflow_state enum", () => {
    const raw = { id: 1, workflow_state: "completed", completion: 100 };
    const p = CanvasProgress.parse(raw);
    expect(p.workflow_state).toBe("completed");

    // Invalid state should fail
    expect(() => CanvasProgress.parse({ id: 2, workflow_state: "invalid" })).toThrow();
  });

  it("rejects invalid data", () => {
    expect(() => CanvasCourse.parse({ name: "no id" })).toThrow();
    expect(() => CanvasStudentResponse.parse({})).toThrow();
  });
});
