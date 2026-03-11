import { Database as SQLiteDatabase } from "bun:sqlite";
/**
 * Database connection — lazy singleton using bun:sqlite + kysely.
 */
import { join } from "node:path";
import { Kysely } from "kysely";
import { BunSqliteDialect } from "kysely-bun-sqlite";
import { findProjectRoot } from "../utils/paths.ts";
import type { Database } from "./schema.ts";

export { findProjectRoot };

let _db: Kysely<Database> | null = null;

/** Create a Kysely instance backed by the given SQLite path (or in-memory). */
export function createDb(path = ":memory:"): Kysely<Database> {
	const sqlite = new SQLiteDatabase(path);
	sqlite.run("PRAGMA journal_mode = WAL");
	sqlite.run("PRAGMA foreign_keys = ON");

	return new Kysely<Database>({
		dialect: new BunSqliteDialect({ database: sqlite }),
	});
}

/** Get or create the singleton DB connection. */
export function getDb(path?: string): Kysely<Database> {
	if (!_db) {
		_db = createDb(path);
	}
	return _db;
}

/** Close the singleton connection (for delete/restore workflows). */
export async function closeDb(): Promise<void> {
	if (_db) {
		await _db.destroy();
		_db = null;
	}
}

/** Resolve the path to cass.db relative to the project root. */
export async function dbPath(from?: string): Promise<string> {
	const root = await findProjectRoot(from);
	if (!root) {
		throw new Error("Could not find cass.toml in any parent directory");
	}
	return join(root, "cass.db");
}
