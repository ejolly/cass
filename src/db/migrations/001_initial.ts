/**
 * Initial schema v16 — simplified from v15:
 *   - Merged canvas_grades into canvas_submissions
 *   - Merged canvas_students into students
 *   - Replaced shadow tables with inline _synced_* columns
 */
import type { Kysely } from "kysely";
import { sql } from "kysely";

export async function up(db: Kysely<unknown>): Promise<void> {
  // Meta
  await db.schema
    .createTable("meta")
    .addColumn("key", "text", (col) => col.primaryKey())
    .addColumn("value", "text", (col) => col.notNull())
    .execute();

  await db
    .insertInto("meta" as never)
    .values({ key: "schema_version", value: "16" } as never)
    .execute();

  // Students (master — includes Canvas-specific fields)
  await db.schema
    .createTable("students")
    .addColumn("canvas_id", "integer", (col) => col.primaryKey())
    .addColumn("github_username", "text", (col) => col.unique())
    .addColumn("name", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("sortable_name", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("email", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("login_id", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("sis_user_id", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("sis_section_id", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("excluded", "integer", (col) => col.notNull().defaultTo(0))
    .execute();

  // Assignments (master)
  await db.schema
    .createTable("assignments")
    .addColumn("slug", "text", (col) => col.primaryKey())
    .addColumn("title", "text", (col) => col.notNull())
    .addColumn("gh_assignment_slug", "text", (col) => col.unique())
    .addColumn("canvas_assignment_id", "integer", (col) => col.unique())
    .addColumn("points_possible", "real", (col) => col.notNull().defaultTo(0))
    .addColumn("deadline", "text")
    .execute();

  // Canvas assignments (with inline synced columns)
  await db.schema
    .createTable("canvas_assignments")
    .addColumn("canvas_id", "integer", (col) => col.primaryKey())
    .addColumn("name", "text", (col) => col.notNull())
    .addColumn("points_possible", "real", (col) => col.notNull().defaultTo(0))
    .addColumn("due_at", "text")
    .addColumn("published", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("assignment_group", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("post_manually", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("_synced_name", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("_synced_points_possible", "real", (col) => col.notNull().defaultTo(0))
    .addColumn("_synced_due_at", "text")
    .addColumn("_synced_published", "integer", (col) => col.notNull().defaultTo(0))
    .execute();

  // Canvas submissions (merged with grades, inline synced column)
  await db.schema
    .createTable("canvas_submissions")
    .addColumn("canvas_user_id", "integer", (col) => col.notNull())
    .addColumn("canvas_assignment_id", "integer", (col) => col.notNull())
    .addColumn("submitted", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("submitted_at", "text")
    .addColumn("late", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("lateness_seconds", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("score", "real")
    .addColumn("workflow_state", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("fetched_at", "real", (col) => col.notNull())
    // Grade fields (merged from canvas_grades)
    .addColumn("posted_grade", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("grade_updated_at", "real", (col) => col.notNull().defaultTo(0))
    // Inline synced baseline
    .addColumn("_synced_posted_grade", "text", (col) => col.notNull().defaultTo(""))
    .execute();

  await db.schema
    .createIndex("canvas_submissions_pk")
    .on("canvas_submissions")
    .columns(["canvas_user_id", "canvas_assignment_id"])
    .unique()
    .execute();

  // GitHub students
  await db.schema
    .createTable("gh_students")
    .addColumn("github_username", "text", (col) => col.primaryKey())
    .addColumn("github_id", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("name", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("email", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("excluded", "integer", (col) => col.notNull().defaultTo(0))
    .execute();

  // GitHub assignments
  await db.schema
    .createTable("gh_assignments")
    .addColumn("slug", "text", (col) => col.primaryKey())
    .addColumn("gh_id", "integer", (col) => col.notNull().unique())
    .addColumn("title", "text", (col) => col.notNull())
    .addColumn("deadline", "text")
    .addColumn("points_possible", "real", (col) => col.notNull().defaultTo(1.0))
    .addColumn("accepted", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("submissions_count", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("passing_count", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("starter_code_repo", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("submittable_files", "text", (col) => col.notNull().defaultTo(""))
    .execute();

  // GitHub submissions
  await db.schema
    .createTable("gh_submissions")
    .addColumn("github_username", "text", (col) => col.notNull())
    .addColumn("assignment_slug", "text", (col) => col.notNull())
    .addColumn("submitted", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("late", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("lateness_seconds", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("repo_name", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("commits_after_deadline", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("commit_count", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("passing", "integer", (col) => col.notNull().defaultTo(0))
    .addColumn("gh_autograder_score", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("last_commit_at", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("last_commit_sha", "text", (col) => col.notNull().defaultTo(""))
    .addColumn("fetched_at", "real", (col) => col.notNull())
    .execute();

  await db.schema
    .createIndex("gh_submissions_pk")
    .on("gh_submissions")
    .columns(["github_username", "assignment_slug"])
    .unique()
    .execute();

  // Indexes for foreign key-like lookups
  await sql`CREATE INDEX IF NOT EXISTS idx_students_github ON students(github_username)`.execute(
    db,
  );
  await sql`CREATE INDEX IF NOT EXISTS idx_assignments_gh ON assignments(gh_assignment_slug)`.execute(
    db,
  );
  await sql`CREATE INDEX IF NOT EXISTS idx_assignments_canvas ON assignments(canvas_assignment_id)`.execute(
    db,
  );
}

export async function down(db: Kysely<unknown>): Promise<void> {
  const tables = [
    "gh_submissions",
    "gh_assignments",
    "gh_students",
    "canvas_submissions",
    "canvas_assignments",
    "assignments",
    "students",
    "meta",
  ];
  for (const table of tables) {
    await db.schema.dropTable(table).ifExists().execute();
  }
}
