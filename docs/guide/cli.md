# CLI

Everything the viewer does also works from the terminal, which makes cass scriptable and usable from coding agents. Every command accepts `--help`. The full generated reference is on the [CLI reference](../reference/cli.md) page.

## Core

```bash
cass init         # interactive setup
cass pull         # fetch students, assignments, submissions
cass status       # local state and sync status
cass view         # open the browser viewer
cass push         # preview and confirm pending Canvas changes
cass push --yes   # skip confirmation
cass revert       # discard pending local changes
```

## Canvas management

Every Canvas resource group has the same shape: `list` shows all items (the bare group runs `list`; a bare `submissions` prints help), `show ID_OR_NAME` shows one item (except `tabs show`, which makes a tab visible), and the write verbs follow. Commands that act on one resource take its ID or its name; if a name matches several items, the command fails and lists the matching IDs. Calendar events take IDs only.

```bash
cass canvas                      # course overview
cass canvas people list          # roster with roles and emails
cass canvas people list --state completed                # also active, invited, inactive
cass canvas people list --enrolled-after 2026-10-01 --json
cass canvas submissions list HW1 --student 123
cass canvas submissions excuse HW1 --student 123 [--apply]
cass canvas submissions excuse --enrolled-after 2026-10-01 [--apply]
cass canvas submissions clear-late HW1 --student 123 --apply
cass canvas files list           # course files as a tree
cass canvas announcements list
cass canvas tabs list            # navigation tabs; tabs show / tabs hide change visibility
cass canvas modules list         # also show / create / publish / delete
cass canvas modules show "Week 1"
cass canvas modules items add "Week 1" --type Assignment --content-id 123 --indent 1
cass canvas modules items update "Week 1" "Reading 1" --title "Reading 1 (revised)" --publish
cass canvas modules items move "Week 1" "Reading 1" --position 1
cass canvas modules items remove "Week 1" "Reading 1" --yes   # the linked content stays
cass canvas assignments list     # also show / create / publish / delete; assignments groups list
cass canvas quizzes list         # see the Quizzes guide for authoring
cass canvas quizzes show "Survey 1"
cass canvas quizzes responses "Survey 1" --csv out.csv   # every student's answers
cass canvas calendar list        # also create / update / delete, by event ID
cass canvas files upload file.pdf --folder readings/week1 --unpublished
cass canvas files mv file.pdf readings/week2   # also files rename / publish / unpublish / delete
cass canvas files folders list   # also folders create / delete
cass canvas announcements create "Title" -m "Body"   # also update / delete
cass canvas tabs hide "Grades"   # also tabs show
cass canvas sync [--apply] [--prune]   # reconcile [[canvas.*]] declarations; --prune removes undeclared module items
cass canvas login --from-chrome  # browser-session auth, see Canvas authentication
cass canvas api GET /courses/{course}/modules --all     # raw API request
cass canvas api PUT /courses/{course}/modules/5 --data 'module[name]=Week1'
```

`modules items add` takes `--type` Assignment, Quiz, File, Page, ExternalUrl or SubHeader, and the matching reference: `--content-id` (Assignment, Quiz, File), `--page-url` (Page), or `--url` and `--title` (ExternalUrl); SubHeader needs `--title`. No other item types are supported. To manage a module's items from `cass.toml`, see [Module items](configuration.md#module-items).

Folder paths are relative to the course files root (no `course files/` prefix). `files upload --folder` and `files mv` create missing folders. `--unpublished` locks new uploads so students cannot see them. `files upload --on-duplicate` defaults to `overwrite`, which replaces a same-named file: Canvas stores the upload as a new file with a new ID and re-points module items and course links to it. `rename` keeps both files. `skip` skips the upload when a file with the same name and size is already there, and overwrites when only the name matches. `files mv` and `files rename` accept `--on-duplicate rename|overwrite`; without it, a name clash fails in Canvas. `files list --folder` takes a folder ID or path. `files folders delete --force` deletes non-empty folders.

`cass canvas api` prints the response body as JSON. `{course}` expands to the configured course ID; `--param KEY=VALUE` adds query parameters and `--json-body` sends a JSON body. To call the API from Python, see the [Python API guide](python-api.md).

### Late enrollments

`people list` shows each person's enrolled-at date. That is the earliest `created_at` among their enrollments, deleted ones included. `--enrolled-after DATE` keeps people of any role first enrolled after DATE; a bare date means midnight in the course time zone. `--state` selects enrollment states (default: active and invited).

`submissions excuse` and `submissions clear-late` take exactly one of `--student ID` (repeatable, needs an ASSIGNMENT) or `--enrolled-after DATE`. Both are dry runs unless you pass `--apply`.

Canvas creates a new assignment's submissions a few seconds after the assignment, so `submissions list`, `excuse` and `clear-late` find none right after you create it. `submissions list` warns when that is the likely reason.

- With `--enrolled-after`, only `StudentEnrollment` students in `active` or `invited` state count, never the Test Student. A submission is picked when its assignment was due before that student enrolled, judged by the student's own due date. Assignments without a due date and unpublished assignments are never touched. An unpublished ASSIGNMENT exits 1. Canvas fills in a new student's due dates a few moments after they enroll, so a student added minutes ago may not be picked yet.
- With `--student` and an explicit ASSIGNMENT, cass makes the change even when the assignment is unpublished or has no due date, and warns.
- `excuse` skips graded submissions unless you pass `--include-graded`, because excusing clears the grade. Any score is protected except Canvas's missing-submission policy score (marked missing, no grader), so a teacher's partial credit on a missing submission is kept. Marking a submission Missing by hand in the Canvas gradebook records you as its grader, so the policy score that follows is protected too; excusing it needs `--include-graded`. Submitted but ungraded work is excused because it has no score to protect; the dry run shows its submitted date.
- `clear-late` sets Canvas's late status to `none`. That clears `late` and `missing` and restores any deducted points on the current submission; the dry run shows the points restored. Canvas resets the status when the student submits again, so a later late resubmission is marked late again: run `clear-late` again after it. If the student resubmitted after being graded, Canvas keeps the deduction until the submission is graded again.
- `clear-late` skips submissions that are not late, excused submissions (setting a late status would un-excuse them), and assignments graded as a group, where Canvas would change every group member's status. Clear those in Canvas. `excuse` is per student, even on group assignments.

## Output and errors

`list` and `show` print tables; `--csv PATH` and `--save PATH` write a file instead.

`--json` prints machine-readable output with Canvas field names: JSON Lines (one object per line) on `list` commands, one object on `quizzes`/`modules`/`assignments show` and on `cass status --json`. It cannot be combined with `--csv` or `--save`. `tabs show` is a write: it takes `--dry-run`, not `--json`.

```bash
cass canvas assignments list --json | jq -r '.name'
cass canvas quizzes show "Survey 1" --json | jq '.questions_source'
cass status --json | jq '.pending_changes'
```

- `files list --json` adds a `kind` field (`file` or `folder`) to each line.
- `modules list --json` has no items; use `modules show --json` for a module with its items.
- `quizzes show --json` adds `questions` and `questions_source`: `questions` when read from the quiz's questions endpoint, `statistics` when that endpoint is closed (concluded courses) and the questions come from the quiz statistics.
- `status --json` has the keys `config_path`, `course_url`, `course_id`, `auth_source`, `db_path`, `course_name`, `counts` (`students`, `assignments`, `submissions`), and `pending_changes`.

stdout carries only data. Hints, progress, prompts, and errors go to stderr, so pipes and redirects receive clean output. A failed command exits 1 with one message; a usage error (unknown option, missing argument) exits 2. To see the full traceback, pass the global `--debug` flag before the subcommand (`cass --debug canvas quizzes list`) or set `CASS_DEBUG=1`.

## Previewing changes

Every command that writes to Canvas takes `--dry-run`. It prints the requests the command would send and sends none; GETs still run.

```bash
cass canvas modules create "Week 9" --dry-run
cass push --dry-run                 # preview pending local changes
cass canvas sync                    # dry run by default
cass canvas sync --apply            # make the changes
```

Reconcile commands such as `sync` preview by default and change Canvas only with `--apply`. Commands that ask for confirmation take `--yes`; without a terminal they exit with code 1 rather than wait for input.

## Data

```bash
cass query students                     # roster
cass query assignments                  # assignment metadata
cass query submissions                  # submissions joined with names
cass query gradebook                    # student x assignment matrix
cass query gradebook --where "score < 50" --order name --limit 20
cass query --sql "select count(*) from canvas_students"
cass backup [--tag NAME]
cass restore PATH
cass delete                             # remove local database
```

## Another course

Every command accepts `--config PATH` (or the `CASS_CONFIG` environment variable) to run against a different `cass.toml`. Credentials and `cass.db` resolve beside that file.

```bash
cass --config ../f25/cass.toml canvas quizzes list
```
