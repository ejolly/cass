/**
 * Database connection — lazy singleton using bun:sqlite + kysely.
 */
import { Database as SQLiteDatabase } from "bun:sqlite";
import { Kysely } from "kysely";
import { BunSqliteDialect } from "kysely-bun-sqlite";
import type { Database } from "./schema.ts";

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

/**
 * Find cass.db by walking up from cwd looking for cass.toml.
 * Returns the directory containing cass.toml, or null if not found.
 */
export function findProjectRoot(from = process.cwd()): string | null {
	let dir = from;
	const { join, dirname } = require("node:path") as typeof import("node:path");

	while (true) {
		const candidate = join(dir, "cass.toml");
		if (Bun.file(candidate).size > 0) {
			return dir;
		}
		const parent = dirname(dir);
		if (parent === dir) return null;
		dir = parent;
	}
}

/** Resolve the path to cass.db relative to the project root. */
export function dbPath(from?: string): string {
	const root = findProjectRoot(from);
	if (!root) {
		throw new Error("Could not find cass.toml in any parent directory");
	}
	const { join } = require("node:path") as typeof import("node:path");
	return join(root, "cass.db");
}
