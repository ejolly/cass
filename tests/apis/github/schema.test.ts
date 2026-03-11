import { describe, expect, it } from "bun:test";
import {
	GHAcceptedAssignment,
	GHAssignmentResponse,
	GHCommit,
	GHRosterEntry,
	GHStudentInfo,
} from "../../../src/apis/github/schema.ts";

describe("GitHub Zod schemas", () => {
	it("parses student info with string coercion for id", () => {
		const raw = { login: "alice", id: 12345, name: "Alice", email: "a@b.com" };
		const student = GHStudentInfo.parse(raw);
		expect(student.login).toBe("alice");
		expect(student.id).toBe("12345"); // coerced to string
	});

	it("parses student info with string id", () => {
		const raw = { login: "bob", id: "67890" };
		const student = GHStudentInfo.parse(raw);
		expect(student.id).toBe("67890");
		expect(student.name).toBe(""); // default
	});

	it("parses assignment response with starter code", () => {
		const raw = {
			id: 5001,
			slug: "hw1",
			title: "Homework 1",
			deadline: "2026-02-01T23:59:00Z",
			accepted: 30,
			submissions: 25,
			passing: 20,
			starter_code_repository: { id: 999, full_name: "org/starter-hw1" },
		};
		const a = GHAssignmentResponse.parse(raw);
		expect(a.slug).toBe("hw1");
		expect(a.starter_code_repository?.full_name).toBe("org/starter-hw1");
	});

	it("handles null starter_code_repository", () => {
		const raw = { id: 5002, slug: "hw2", title: "Homework 2" };
		const a = GHAssignmentResponse.parse(raw);
		expect(a.starter_code_repository).toBeNull();
		expect(a.deadline).toBeNull();
	});

	it("parses accepted assignment", () => {
		const raw = {
			id: 1,
			students: [{ id: 1, login: "alice" }],
			repository: { id: 100, full_name: "org/hw1-alice" },
			commit_count: 5,
			submitted: true,
			passing: true,
			grade: "10/10",
		};
		const aa = GHAcceptedAssignment.parse(raw);
		expect(aa.students[0]!.login).toBe("alice");
		expect(aa.repository?.full_name).toBe("org/hw1-alice");
	});

	it("parses commit", () => {
		const raw = {
			sha: "abc123",
			commit: { committer: { date: "2026-01-15T10:00:00Z" } },
		};
		const c = GHCommit.parse(raw);
		expect(c.sha).toBe("abc123");
		expect(c.commit.committer.date).toBe("2026-01-15T10:00:00Z");
	});

	it("parses roster entry with defaults", () => {
		const raw = { github_username: "alice" };
		const r = GHRosterEntry.parse(raw);
		expect(r.github_username).toBe("alice");
		expect(r.roster_identifier).toBe("");
		expect(r.student_repository_name).toBe("");
	});
});
