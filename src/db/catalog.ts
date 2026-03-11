/**
 * Table capabilities — typed metadata for the DB catalog.
 * Shared by CLI and viewer to determine what operations are allowed per table.
 */
import type { TableName } from "./schema.ts";

// ─── Viewer table names (excludes meta + shadow tables) ─────────────

/** Tables visible in the viewer, ordered by viewer_rank. */
export type ViewerTableName =
	| "canvas_grades"
	| "canvas_assignments"
	| "canvas_submissions"
	| "gh_submissions"
	| "gh_students"
	| "gh_assignments"
	| "students"
	| "assignments";

export interface TableCapability {
	editable: boolean;
	pushable: boolean;
	pullGuarded: boolean;
	viewerRank: number;
	/** If set, only these columns are editable. null = all columns editable. */
	editableColumns: string[] | null;
}

export const TABLE_CAPABILITIES: Record<ViewerTableName, TableCapability> = {
	canvas_grades: {
		editable: true,
		pushable: true,
		pullGuarded: true,
		viewerRank: 0,
		editableColumns: null,
	},
	canvas_assignments: {
		editable: true,
		pushable: true,
		pullGuarded: true,
		viewerRank: 1,
		editableColumns: null,
	},
	canvas_submissions: {
		editable: false,
		pushable: false,
		pullGuarded: false,
		viewerRank: 2,
		editableColumns: null,
	},
	gh_submissions: {
		editable: false,
		pushable: false,
		pullGuarded: false,
		viewerRank: 10,
		editableColumns: null,
	},
	gh_students: {
		editable: true,
		pushable: false,
		pullGuarded: false,
		viewerRank: 11,
		editableColumns: ["excluded"],
	},
	gh_assignments: {
		editable: false,
		pushable: false,
		pullGuarded: false,
		viewerRank: 12,
		editableColumns: null,
	},
	students: {
		editable: false,
		pushable: false,
		pullGuarded: false,
		viewerRank: 20,
		editableColumns: null,
	},
	assignments: {
		editable: false,
		pushable: false,
		pullGuarded: false,
		viewerRank: 21,
		editableColumns: null,
	},
};

// ─── Pushable columns per table ─────────────────────────────────────

export const CANVAS_PUSHABLE = {
	canvas_assignments: ["name", "points_possible", "due_at", "published"] as const,
	canvas_grades: ["posted_grade"] as const,
} as const;

// ─── Derived sets ───────────────────────────────────────────────────

/** Tables hidden from the viewer. */
export const EXCLUDED_TABLES: TableName[] = [
	"meta",
	"canvas_students",
	"_canvas_assignments_synced",
	"_canvas_grades_synced",
];

/** Tables available for export, in order. */
export const EXPORTABLE_TABLES: TableName[] = [
	"students",
	"assignments",
	"gh_students",
	"canvas_students",
	"gh_assignments",
	"canvas_assignments",
	"gh_submissions",
	"canvas_submissions",
	"canvas_grades",
];

// ─── Helper functions ───────────────────────────────────────────────

function getCap(table: string): TableCapability | undefined {
	return TABLE_CAPABILITIES[table as ViewerTableName];
}

export function isEditable(table: string): boolean {
	return getCap(table)?.editable ?? false;
}

export function isPushable(table: string): boolean {
	return getCap(table)?.pushable ?? false;
}

export function isPullGuarded(table: string): boolean {
	return getCap(table)?.pullGuarded ?? false;
}

/** Returns restricted editable columns, or null if all columns are editable. */
export function getEditableColumns(table: string): string[] | null {
	const cap = getCap(table);
	if (!cap?.editable) return null;
	return cap.editableColumns;
}
