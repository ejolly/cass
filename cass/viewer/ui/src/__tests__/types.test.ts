import { describe, it, expect } from "vitest";
import { classifyTable } from "$lib/types.js";

describe("classifyTable", () => {
  it("classifies canvas tables", () => {
    expect(classifyTable("canvas_grades")).toBe("canvas");
    expect(classifyTable("canvas_assignments")).toBe("canvas");
    expect(classifyTable("canvas_students")).toBe("canvas");
    expect(classifyTable("canvas_submissions")).toBe("canvas");
  });

  it("classifies github tables", () => {
    expect(classifyTable("gh_submissions")).toBe("github");
    expect(classifyTable("gh_students")).toBe("github");
    expect(classifyTable("gh_grades")).toBe("github");
    expect(classifyTable("gh_assignments")).toBe("github");
  });

  it("classifies combined/unified tables", () => {
    expect(classifyTable("students")).toBe("combined");
    expect(classifyTable("assignments")).toBe("combined");
  });
});
