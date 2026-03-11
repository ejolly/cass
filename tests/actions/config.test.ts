import { describe, expect, it } from "bun:test";
import {
  type Config,
  classroomStatus,
  hasCanvas,
  hasClassroom,
  hasClassroomUrl,
  parseCanvasCourseUrl,
  parseClassroomUrl,
} from "@/actions/config.ts";

const baseConfig: Config = {
  root: "/tmp/test",
  classroomUrl: "",
  classroomUrlId: 0,
  classroomGhId: 0,
  classroomSlug: "",
  classroomTitle: "",
  org: "",
  canvasBaseUrl: "",
  canvasCourseId: 0,
  canvasModules: [],
  canvasAssignments: [],
};

describe("config", () => {
  describe("parseCanvasCourseUrl", () => {
    it("parses valid Canvas URLs", () => {
      const result = parseCanvasCourseUrl("https://canvas.ucsd.edu/courses/12345");
      expect(result).toEqual(["https://canvas.ucsd.edu", 12345]);
    });

    it("returns null for invalid URLs", () => {
      expect(parseCanvasCourseUrl("not a url")).toBeNull();
      expect(parseCanvasCourseUrl("https://canvas.edu/")).toBeNull();
    });
  });

  describe("parseClassroomUrl", () => {
    it("extracts URL ID from classroom URL", () => {
      const result = parseClassroomUrl(
        "https://classroom.github.com/classrooms/232475786-201b-w26",
      );
      expect(result).toBe(232475786);
    });

    it("returns null for invalid URLs", () => {
      expect(parseClassroomUrl("not a url")).toBeNull();
    });
  });

  describe("computed properties", () => {
    it("hasClassroomUrl requires both url and url_id", () => {
      expect(hasClassroomUrl(baseConfig)).toBe(false);
      expect(
        hasClassroomUrl({
          ...baseConfig,
          classroomUrl: "https://example.com",
          classroomUrlId: 123,
        }),
      ).toBe(true);
    });

    it("hasClassroom requires gh_id", () => {
      expect(
        hasClassroom({
          ...baseConfig,
          classroomUrl: "https://example.com",
          classroomUrlId: 123,
          classroomGhId: 456,
        }),
      ).toBe(true);
    });

    it("classroomStatus returns correct states", () => {
      expect(classroomStatus(baseConfig)).toEqual({ tag: "missing" });

      expect(
        classroomStatus({
          ...baseConfig,
          classroomUrl: "https://example.com",
          classroomUrlId: 123,
        }),
      ).toEqual({ tag: "pending", url: "https://example.com", urlId: 123 });

      expect(
        classroomStatus({
          ...baseConfig,
          classroomUrl: "https://example.com",
          classroomUrlId: 123,
          classroomGhId: 456,
        }),
      ).toEqual({ tag: "configured", ghId: 456 });
    });

    it("hasCanvas requires both base_url and course_id", () => {
      expect(hasCanvas(baseConfig)).toBe(false);
      expect(
        hasCanvas({ ...baseConfig, canvasBaseUrl: "https://canvas.edu", canvasCourseId: 1 }),
      ).toBe(true);
    });
  });
});
