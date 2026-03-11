import { join } from "node:path";
/**
 * Repo cloning/pulling via Bun.$ + p-limit concurrency.
 */
import { $ } from "bun";
import pLimit from "p-limit";

/** Canvas "Last, First" -> "last-first" directory name. */
export function sanitizeStudentDir(sortableName: string, githubUsername: string): string {
  if (!sortableName) return githubUsername.toLowerCase();
  return sortableName
    .toLowerCase()
    .replace(/,/g, "")
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

type CloneResult = "cloned" | "updated" | "up-to-date";

/** Clone or pull a single repo. */
async function cloneOrPull(repoUrl: string, dest: string): Promise<CloneResult> {
  const gitHead = join(dest, ".git", "HEAD");
  const gitExists = await Bun.file(gitHead)
    .exists()
    .catch(() => false);

  if (gitExists) {
    // Fetch and check for changes
    await $`git -C ${dest} fetch origin`.quiet();
    const diff = await $`git -C ${dest} diff HEAD..origin/HEAD --stat`.quiet();
    if (diff.stdout.toString().trim()) {
      await $`git -C ${dest} reset --hard origin/HEAD`.quiet();
      return "updated";
    }
    return "up-to-date";
  }

  // Clone
  await $`git clone --depth 1 ${repoUrl} ${dest}`.quiet();
  return "cloned";
}

export interface PullGHOptions {
  limitStudents?: number;
  limitAssignments?: number;
  maxConcurrent?: number;
  onProgress?: (msg: string) => void;
}

export interface PullGHCounts {
  cloned: number;
  updated: number;
  upToDate: number;
  skipped: number;
  errors: number;
}

/**
 * Clone/update repos for all assignment-student combinations.
 * Uses p-limit for bounded concurrency.
 */
export async function pullRepos(
  repoMap: Map<string, string>,
  studentDirs: Map<string, string>,
  assignmentSlug: string,
  baseDir: string,
  opts: PullGHOptions = {},
): Promise<PullGHCounts> {
  const limit = pLimit(opts.maxConcurrent ?? 8);
  const counts: PullGHCounts = {
    cloned: 0,
    updated: 0,
    upToDate: 0,
    skipped: 0,
    errors: 0,
  };

  const tasks: Promise<void>[] = [];

  for (const [handle, repoName] of repoMap) {
    const studentDir = studentDirs.get(handle);
    if (!studentDir) {
      counts.skipped++;
      continue;
    }

    const dest = join(baseDir, studentDir, assignmentSlug);
    const repoUrl = `https://github.com/${repoName}.git`;

    tasks.push(
      limit(async () => {
        try {
          const result = await cloneOrPull(repoUrl, dest);
          counts[result === "up-to-date" ? "upToDate" : result]++;
          opts.onProgress?.(`${handle}: ${result}`);
        } catch (e) {
          counts.errors++;
          opts.onProgress?.(`${handle}: error - ${e instanceof Error ? e.message : e}`);
        }
      }),
    );
  }

  await Promise.all(tasks);
  return counts;
}
