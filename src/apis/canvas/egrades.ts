/**
 * eGrades CSV generation — UCSD 5-column format.
 * Uses papaparse for CSV output.
 */
import type { KyInstance } from "ky";
import type { Kysely } from "kysely";
import Papa from "papaparse";
import type { Database } from "../../db/schema.ts";
import { getPaginated } from "./client.ts";
import {
	CanvasCourse,
	CanvasEnrollment,
	type CanvasGradingSchemeEntry,
	CanvasGradingStandard,
} from "./schema.ts";

/** Convert a percentage score to a letter grade using a Canvas grading scheme. */
export function scoreToLetter(
	pct: number | null | undefined,
	scheme: CanvasGradingSchemeEntry[],
): string {
	if (pct == null || scheme.length === 0) return "";

	// Canvas scheme values are fractions (e.g., 0.94 = 94%)
	const fraction = pct / 100;
	const sorted = [...scheme].sort((a, b) => b.value - a.value);

	for (const entry of sorted) {
		if (fraction >= entry.value) return entry.name;
	}

	// Below all thresholds — return the lowest grade
	return sorted[sorted.length - 1]?.name ?? "";
}

/** Parse "Last, First" sortable name format. */
export function parseSortableName(sortableName: string): [string, string] {
	const commaIdx = sortableName.indexOf(",");
	if (commaIdx === -1) return [sortableName.trim(), ""];
	return [sortableName.slice(0, commaIdx).trim(), sortableName.slice(commaIdx + 1).trim()];
}

export interface EgradesResult {
	path: string;
	rowCount: number;
	warnings: string[];
}

/** Generate eGrades CSV from Canvas enrollments + local DB data. */
export async function generateEgrades(
	client: KyInstance,
	courseId: number,
	db: Kysely<Database>,
	output = "egrades.csv",
): Promise<EgradesResult> {
	const warnings: string[] = [];

	// 1. Get course + grading standard
	const course = CanvasCourse.parse(await client.get(`courses/${courseId}`).json());
	if (!course.grading_standard_id) {
		throw new Error("Course has no grading standard set. Configure one in Canvas first.");
	}

	// 2. Get grading scheme
	const standards = await getPaginated<unknown>(
		client,
		`courses/${courseId}/grading_standards`,
	).then((items) => items.map((i) => CanvasGradingStandard.parse(i)));

	const standard = standards.find((s) => s.id === course.grading_standard_id);
	if (!standard) {
		throw new Error(`Grading standard ${course.grading_standard_id} not found.`);
	}

	// 3. Get enrollments with final scores
	const enrollments = await getPaginated<unknown>(client, `courses/${courseId}/enrollments`, {
		type: "StudentEnrollment",
		include: "total_scores",
	}).then((items) => items.map((i) => CanvasEnrollment.parse(i)));

	const scoreMap = new Map<number, number | null>();
	for (const e of enrollments) {
		const score = e.grades?.final_score ?? e.grades?.current_score ?? null;
		scoreMap.set(e.user_id, score);
	}

	// 4. Get local student data
	const students = await db
		.selectFrom("canvas_students")
		.select(["canvas_id", "sortable_name", "sis_user_id", "sis_section_id"])
		.where("sis_user_id", "!=", "")
		.execute();

	// 5. Build CSV rows
	const rows: string[][] = [];
	for (const s of students) {
		const score = scoreMap.get(s.canvas_id);
		if (score == null) {
			warnings.push(`No final score for ${s.sortable_name} (canvas_id=${s.canvas_id})`);
			continue;
		}

		const [lastName, firstName] = parseSortableName(s.sortable_name);
		const grade = scoreToLetter(score, standard.grading_scheme);
		rows.push([lastName, firstName, s.sis_user_id, s.sis_section_id, grade]);
	}

	// Sort by last name, first name
	rows.sort((a, b) => {
		const lastCmp = (a[0] ?? "").toLowerCase().localeCompare((b[0] ?? "").toLowerCase());
		if (lastCmp !== 0) return lastCmp;
		return (a[1] ?? "").toLowerCase().localeCompare((b[1] ?? "").toLowerCase());
	});

	// 6. Write CSV
	const csv = Papa.unparse({
		fields: ["Last Name", "First Name", "Student ID", "SectionId", "Final_Assigned_Egrade"],
		data: rows,
	});

	await Bun.write(output, csv);

	return { path: output, rowCount: rows.length, warnings };
}
