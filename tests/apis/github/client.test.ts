import { describe, expect, it } from "bun:test";
import { assignmentsToDB, studentsToDB } from "../../../src/apis/github/classroom.ts";
import { sanitizeStudentDir } from "../../../src/apis/github/fetch.ts";
import type { GHAssignmentResponse, GHStudentInfo } from "../../../src/apis/github/schema.ts";

describe("GitHub utils", () => {
  describe("sanitizeStudentDir", () => {
    it("converts sortable name to directory format", () => {
      expect(sanitizeStudentDir("Smith, Alice", "alice-gh")).toBe("smith-alice");
    });

    it("handles names with extra spaces", () => {
      expect(sanitizeStudentDir("De La Cruz, Maria", "maria")).toBe("de-la-cruz-maria");
    });

    it("falls back to github username", () => {
      expect(sanitizeStudentDir("", "alice-gh")).toBe("alice-gh");
    });

    it("strips special characters", () => {
      expect(sanitizeStudentDir("O'Brien, Pat", "pat")).toBe("obrien-pat");
    });
  });

  describe("assignmentsToDB", () => {
    it("converts API responses to DB rows", () => {
      const assignments: GHAssignmentResponse[] = [
        {
          id: 5001,
          slug: "hw1",
          title: "Homework 1",
          deadline: "2026-02-01T23:59:00Z",
          accepted: 30,
          submissions: 25,
          passing: 20,
          starter_code_repository: { id: 999, full_name: "org/starter-hw1" },
        },
      ];
      const rows = assignmentsToDB(assignments);
      expect(rows).toHaveLength(1);
      expect(rows[0]!.slug).toBe("hw1");
      expect(rows[0]!.gh_id).toBe(5001);
      expect(rows[0]!.starter_code_repo).toBe("org/starter-hw1");
    });

    it("handles null starter_code_repository", () => {
      const assignments: GHAssignmentResponse[] = [
        {
          id: 5002,
          slug: "hw2",
          title: "Homework 2",
          deadline: null,
          accepted: 0,
          submissions: 0,
          passing: 0,
          starter_code_repository: null,
        },
      ];
      const rows = assignmentsToDB(assignments);
      expect(rows[0]!.starter_code_repo).toBe("");
    });
  });

  describe("studentsToDB", () => {
    it("converts student info to DB rows", () => {
      const students: GHStudentInfo[] = [
        { login: "alice", id: "12345", name: "Alice Smith", email: "a@b.com" },
        { login: "bob", id: "0", name: "", email: "" },
      ];
      const rows = studentsToDB(students);
      expect(rows).toHaveLength(2);
      expect(rows[0]!.github_username).toBe("alice");
      expect(rows[0]!.github_id).toBe(12345);
      expect(rows[1]!.github_id).toBe(0);
    });
  });
});
