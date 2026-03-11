import { requireConfig, requireDb } from "@/cli/helpers.ts";
/**
 * pull-repos — clone/update GitHub repos.
 */
import type { CAC } from "cac";
import consola from "consola";

export function register(cli: CAC): void {
  cli
    .command("pull-repos", "Clone/update GitHub repos")
    .option("-a, --assignment <slug>", "Specific assignment slug")
    .option("-s, --limit-students <n>", "Max students", { default: 0 })
    .option("-n, --limit-assignments <n>", "Max assignments", { default: 0 })
    .action(
      async (opts: { assignment?: string; limitStudents?: number; limitAssignments?: number }) => {
        const cfg = await requireConfig();
        const { hasClassroom } = await import("@/actions/config.ts");
        if (!hasClassroom(cfg)) {
          consola.error("GitHub Classroom not configured");
          process.exit(1);
        }

        const db = await requireDb(cfg);
        const { buildRepoMap } = await import("@/apis/github/classroom.ts");
        const { pullRepos, sanitizeStudentDir } = await import("@/apis/github/fetch.ts");
        const { join } = await import("node:path");

        try {
          let ghAssignments = await db.selectFrom("gh_assignments").selectAll().execute();

          if (opts.assignment) {
            ghAssignments = ghAssignments.filter((a) => a.slug === opts.assignment);
            if (ghAssignments.length === 0) {
              consola.error(`Assignment not found: ${opts.assignment}`);
              process.exit(1);
            }
          }
          if (opts.limitAssignments && opts.limitAssignments > 0) {
            ghAssignments = ghAssignments.slice(0, opts.limitAssignments);
          }

          const students = await db.selectFrom("students").selectAll().execute();
          const studentDirs = new Map<string, string>();
          for (const s of students) {
            if (s.github_username) {
              studentDirs.set(
                s.github_username,
                sanitizeStudentDir(s.sortable_name, s.github_username),
              );
            }
          }

          const baseDir = join(cfg.root, "repos");

          for (const assignment of ghAssignments) {
            consola.info(`Pulling repos for ${assignment.slug}...`);
            const repoMap = await buildRepoMap(assignment.gh_id);

            const counts = await pullRepos(repoMap, studentDirs, assignment.slug, baseDir, {
              limitStudents: opts.limitStudents || undefined,
            });

            consola.success(
              `${assignment.slug}: ${counts.cloned} cloned, ${counts.updated} updated, ${counts.upToDate} up-to-date, ${counts.errors} errors`,
            );
          }
        } finally {
          await db.destroy();
        }
      },
    );
}
