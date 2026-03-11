/**
 * Dynamic table operations — variable table/column names via kysely.
 * Used for `cass query --sql` escape hatch and viewer edit operations.
 */
import { type Kysely, sql } from "kysely";
import type { Database, TableName } from "./schema.ts";

/** Update a single cell in any table (for viewer edits). */
export async function updateCell(
	db: Kysely<Database>,
	table: TableName,
	pkColumns: string[],
	pkValues: (string | number)[],
	column: string,
	value: string | number | null,
): Promise<void> {
	let query = db.updateTable(table).set({ [column]: value } as never);

	for (let i = 0; i < pkColumns.length; i++) {
		query = query.where(sql.ref(pkColumns[i]!) as never, "=", pkValues[i]! as never);
	}

	await query.execute();
}

/** Execute a raw SQL query (for `cass query --sql`). */
export async function rawQuery(
	db: Kysely<Database>,
	sqlStr: string,
): Promise<Record<string, unknown>[]> {
	const result = await sql.raw(sqlStr).execute(db);
	return result.rows as Record<string, unknown>[];
}

/** Get all rows from a table (for export). */
export async function getAllRows(
	db: Kysely<Database>,
	table: TableName,
): Promise<Record<string, unknown>[]> {
	return db.selectFrom(table).selectAll().execute() as Promise<Record<string, unknown>[]>;
}

/** Get table column info via SQLite pragma. */
export async function getTableColumns(
	db: Kysely<Database>,
	table: TableName,
): Promise<Array<{ name: string; type: string; notnull: number; pk: number }>> {
	const result = await sql<{
		name: string;
		type: string;
		notnull: number;
		pk: number;
	}>`PRAGMA table_info(${sql.ref(table)})`.execute(db);
	return result.rows;
}
