/**
 * Canvas grade push workflow — shared between CLI and viewer.
 */
import type { KyInstance } from "ky";
import type { Kysely } from "kysely";
import type { CanvasSubmission, Database } from "../../db/schema.ts";
import { waitForProgress } from "./client.ts";
import { CanvasProgress } from "./schema.ts";

const INVALID_GRADES = new Set([undefined, null, "", "-", "?"]);

/** Check if a grade value is valid for pushing. */
export function isValidGrade(grade: string | null | undefined): boolean {
	return !INVALID_GRADES.has(grade);
}

/** assignment_id -> { user_id -> grade_string } */
export type GradeData = Record<string, Record<string, string>>;

/** Convert pending submission rows (with grade changes) to push data, filtering invalid grades. */
export function buildGradePushData(submissions: CanvasSubmission[]): [GradeData, number] {
	const data: GradeData = {};
	let skipped = 0;

	for (const s of submissions) {
		if (!isValidGrade(s.posted_grade)) {
			skipped++;
			continue;
		}
		const aidKey = String(s.canvas_assignment_id);
		if (!data[aidKey]) {
			data[aidKey] = {};
		}
		data[aidKey]![String(s.canvas_user_id)] = s.posted_grade;
	}

	return [data, skipped];
}

export interface PushPreviewItem {
	name: string;
	canvasId: number;
	count: number;
	postManually: boolean;
}

/** Build a per-assignment push preview. */
export async function buildPushPreview(
	db: Kysely<Database>,
	gradeData: GradeData,
): Promise<PushPreviewItem[]> {
	const preview: PushPreviewItem[] = [];

	for (const [aidStr, grades] of Object.entries(gradeData)) {
		const aid = Number(aidStr);
		const row = await db
			.selectFrom("canvas_assignments")
			.select(["name", "post_manually"])
			.where("canvas_id", "=", aid)
			.executeTakeFirst();

		preview.push({
			name: row?.name ?? `Assignment ${aid}`,
			canvasId: aid,
			count: Object.keys(grades).length,
			postManually: row?.post_manually === 1,
		});
	}

	return preview;
}

export type PushResult =
	| { ok: true; canvasAssignmentId: number; count: number }
	| { ok: false; error: string; canvasAssignmentId?: number };

/** Push grades to Canvas via bulk update endpoint. */
export async function pushGrades(
	client: KyInstance,
	courseId: number,
	gradeData: GradeData,
): Promise<PushResult[]> {
	const results: PushResult[] = [];

	for (const [aidStr, grades] of Object.entries(gradeData)) {
		const aid = Number(aidStr);
		try {
			// Build the bulk grade_data payload
			const gradePayload: Record<string, { posted_grade: string }> = {};
			for (const [uid, grade] of Object.entries(grades)) {
				gradePayload[uid] = { posted_grade: grade };
			}

			const raw = await client
				.post(`courses/${courseId}/assignments/${aid}/submissions/update_grades`, {
					json: { grade_data: gradePayload },
				})
				.json();

			const progress = CanvasProgress.parse(raw);
			await waitForProgress(client, progress.id);

			results.push({ ok: true, canvasAssignmentId: aid, count: Object.keys(grades).length });
		} catch (e) {
			results.push({
				ok: false,
				error: e instanceof Error ? e.message : String(e),
				canvasAssignmentId: aid,
			});
		}
	}

	return results;
}

/** Push assignment field updates to Canvas. */
export async function pushAssignments(
	client: KyInstance,
	courseId: number,
	updatesByCanvasId: Record<number, Record<string, unknown>>,
): Promise<PushResult[]> {
	const results: PushResult[] = [];

	for (const [idStr, updates] of Object.entries(updatesByCanvasId)) {
		const cid = Number(idStr);
		try {
			await client
				.put(`courses/${courseId}/assignments/${cid}`, {
					json: { assignment: updates },
				})
				.json();

			results.push({ ok: true, canvasAssignmentId: cid, count: 1 });
		} catch (e) {
			results.push({
				ok: false,
				error: e instanceof Error ? e.message : String(e),
				canvasAssignmentId: cid,
			});
		}
	}

	return results;
}
