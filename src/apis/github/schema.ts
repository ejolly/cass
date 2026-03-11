/**
 * GitHub API Zod schemas — each definition = runtime validator + static type.
 */
import { z } from "zod";

export const GHStudentInfo = z.object({
	login: z.string(),
	id: z.union([z.string(), z.number()]).transform(String).default(""),
	name: z.string().default(""),
	email: z.string().default(""),
});
export type GHStudentInfo = z.infer<typeof GHStudentInfo>;

export const GHStarterCodeRepo = z.object({
	id: z.number().default(0),
	full_name: z.string().default(""),
});
export type GHStarterCodeRepo = z.infer<typeof GHStarterCodeRepo>;

export const GHAssignmentResponse = z.object({
	id: z.number(),
	slug: z.string(),
	title: z.string(),
	deadline: z.string().nullable().default(null),
	accepted: z.number().default(0),
	submissions: z.number().default(0),
	passing: z.number().default(0),
	starter_code_repository: GHStarterCodeRepo.nullable().default(null),
});
export type GHAssignmentResponse = z.infer<typeof GHAssignmentResponse>;

export const GHStudentRef = z.object({
	id: z.number(),
	login: z.string(),
});
export type GHStudentRef = z.infer<typeof GHStudentRef>;

export const GHRepository = z.object({
	id: z.number(),
	full_name: z.string(),
});
export type GHRepository = z.infer<typeof GHRepository>;

export const GHAcceptedAssignment = z.object({
	id: z.number(),
	students: z.array(GHStudentRef).default([]),
	repository: GHRepository.nullable().default(null),
	commit_count: z.number().default(0),
	submitted: z.boolean().default(false),
	passing: z.boolean().default(false),
	grade: z.string().default(""),
});
export type GHAcceptedAssignment = z.infer<typeof GHAcceptedAssignment>;

export const GHCommitter = z.object({
	date: z.string(),
});

export const GHCommitInfo = z.object({
	committer: GHCommitter,
});

export const GHCommit = z.object({
	sha: z.string(),
	commit: GHCommitInfo,
});
export type GHCommit = z.infer<typeof GHCommit>;

export const GHRosterEntry = z.object({
	github_username: z.string(),
	roster_identifier: z.string().default(""),
	student_repository_name: z.string().default(""),
	student_repository_url: z.string().default(""),
	submission_timestamp: z.string().default(""),
	points_awarded: z.string().default(""),
	points_available: z.string().default(""),
});
export type GHRosterEntry = z.infer<typeof GHRosterEntry>;

export const GHContentItem = z.object({
	type: z.string(),
	name: z.string(),
	download_url: z.string().nullable().default(null),
});
export type GHContentItem = z.infer<typeof GHContentItem>;
