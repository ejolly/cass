/**
 * Shared path utilities — project root discovery.
 */
import { dirname, join } from "node:path";

/**
 * Walk up from `start` looking for cass.toml.
 * Returns the directory containing cass.toml, or null if not found.
 */
export async function findProjectRoot(start = process.cwd()): Promise<string | null> {
	let dir = start;
	while (true) {
		const candidate = join(dir, "cass.toml");
		if (await Bun.file(candidate).exists()) return dir;
		const parent = dirname(dir);
		if (parent === dir) return null;
		dir = parent;
	}
}
