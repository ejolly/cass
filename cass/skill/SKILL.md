---
name: cass
description: Drive a Canvas LMS course from the terminal with the cass CLI. Use for any Canvas task in a directory with a cass.toml — roster, modules and module items, assignments, quizzes and surveys (create, edit questions, download responses), files and folders, announcements, calendar, tabs, submissions and late enrollments, grades — or for raw Canvas API calls through cass.
---

# cass

<!-- --8<-- [start:body] -->
cass is a CLI over the Canvas REST API for one course, set by `cass.toml`. `--help` on any command is the full truth; this skill tells you which command fits a task and what Canvas does that `--help` won't say.

## Before you act

1. Run `cass status` first. It shows the config path, course, auth source and pending local edits. `cass status --json` gives the same thing as one object.
2. To target another course, pass `--config PATH` before the subcommand, as in `cass --config ../f25/cass.toml canvas quizzes list`, or set `CASS_CONFIG`. Credentials and `cass.db` resolve beside that file.
3. On an error, rerun with `cass --debug …` for the traceback. Exit 1 means the command failed, or that `cass push` or `cass canvas sync` held back, refused or failed part of the work and did the rest. Exit 2 means a usage error.

## Safety rules

- **Dry run every write first.** Writes to Canvas take `--dry-run`, which prints the planned requests and sends none (`cass push --dry-run` prints a comparison with Canvas instead). The exceptions are `cass canvas quizzes preview`, which leaves a teacher preview attempt on Canvas, and `cass canvas quizzes responses`, which has Canvas generate a report. Reconcile commands are dry runs unless you pass `--apply`: `cass canvas sync`, `cass canvas quizzes update QUIZ --from FILE`, `cass canvas submissions excuse` and `cass canvas submissions clear-late`.
- **Show the plan and wait.** Paste the dry-run output to the user. Run the real command, or add `--apply`, only after they agree.
- **Deletes, `items remove`, `cass push`, `cass revert` and `cass restore` need `--yes`.** You have no TTY, so a prompting command exits 1 without it. Pass `--yes` only after the user approved that dry run. `cass revert` has no `--dry-run`: run it without `--yes` to print what it would drop, which is every pending edit, and show the user.
- **`--prune --apply` deletes without asking.** `cass canvas sync` and `cass canvas quizzes update --questions` take no `--yes`; get approval of the dry run first.
- **Never publish unless asked.** Don't pass `--publish` or run `publish` verbs unless the user asked. `cass canvas files upload` locks a new file unless you pass `--publish`, and an overwrite keeps the existing file's lock. Announcements and calendar events are visible to students as soon as they're created; there is no unpublished state.
- **Leave out what you don't mean to change.** In `cass.toml` and quiz files, an omitted `published`, or any other omitted quiz setting, leaves the live value as it is. Only new content gets defaults: unpublished, one attempt. Write `published` only when the user asked to publish or unpublish.
- **Quizzes students have finished are locked.** cass refuses to delete such a quiz, its assignment or its assignment group, or to change its questions, points or scoring settings. It also refuses when it can't check for attempts. No flag overrides this; tell the user to use the Canvas web app. `cass canvas api` doesn't check, so never use it to get around a refusal.
- **Pushing can post grades.** On assignments that post manually, `cass push` makes every graded submission visible to students, and the dry run doesn't show it. Tell the user first.
- **Use the public API only.** In Python, use `CanvasClient` public methods. Never `_client`.

## Task → command

| Task | Command |
|---|---|
| Course overview | `cass canvas` |
| List or inspect anything | `cass canvas assignments list --json`; `show` for one module, assignment or quiz, by ID or name |
| Roster, enrollment dates | `cass canvas people list --json` (`--state completed`, `--enrolled-after DATE`) |
| Module contents | `cass canvas modules show "Week 1" --json` |
| Add, edit, reorder or remove module items | `cass canvas modules items add`, `update`, `move`, `remove` |
| Declare modules, items, assignments and quizzes | edit `cass.toml`, then `cass canvas sync`, then `cass canvas sync --apply` |
| Remove undeclared module items | `cass canvas sync --prune --apply` |
| Readings and files | `cass canvas files upload notes.pdf --folder readings/week1 --dry-run` |
| File tree, folders | `cass canvas files list --json`; `cass canvas files folders list` |
| Move, rename, hide or show a file | `cass canvas files mv`, `rename`, `unpublish`, `publish` |
| Create a quiz or survey | write a quiz file, then `cass canvas quizzes create --from quizzes/survey.toml --dry-run` |
| Edit quiz settings | `cass canvas quizzes update QUIZ --from FILE`, then add `--apply` |
| Edit quiz questions | `cass canvas quizzes export QUIZ -o FILE`, edit it, then `cass canvas quizzes update QUIZ --from FILE --questions` |
| See question IDs and groups, or a student's view | `cass canvas quizzes questions QUIZ --json`; `cass canvas quizzes preview QUIZ` |
| Pull survey or quiz answers | `cass canvas quizzes responses QUIZ --csv responses.csv` |
| Submissions and scores | `cass canvas submissions list HW1 --json` |
| Late-enrolled students | `cass canvas submissions excuse --enrolled-after DATE`; `cass canvas submissions clear-late --enrolled-after DATE` |
| Assignments, groups | `cass canvas assignments create "HW 3" --group Labs --due "2026-10-20 23:59" --dry-run` |
| Announcements | `cass canvas announcements create "Title" -m "<p>Body</p>" --dry-run` |
| Calendar | `cass canvas calendar create "Review" --start "2026-10-20 10:00" --dry-run` |
| Navigation tabs | `cass canvas tabs list`; `cass canvas tabs hide Grades --dry-run` |
| Read grades | `cass pull`, then `cass query submissions --where "score < 50"`; `cass query gradebook` for the student × assignment matrix. Grades are as entered, before late deductions; `score` is after them. Relay the students and assignments pull removed and the local grades it kept; reverting a kept grade can lose it (`references/grades.md`) |
| Push grade and assignment edits made in `cass view` | `cass push --dry-run`, then `cass push --yes`. Conflicts, grades above points possible and cleared grades are held back and stay pending; add `--overwrite-conflicts`, `--allow-over-points` or `--allow-clears` only after the user approves every such row. Some rows no flag can send. Read `references/grades.md` first |
| Anything else | `cass canvas api` (see below) |

Commands take an ID or a name, and an ambiguous name fails and lists the matching IDs. Calendar events and `--student` take IDs only. Times are course-local (`YYYY-MM-DD HH:MM`) unless they carry an offset.

## Output

- `--json` prints JSON Lines on `list` commands, `quizzes questions` and `quizzes preview`, and a single object on `show` and `cass status --json`, using Canvas field names. It can't be combined with `--csv` or `--save`.
- stdout carries only data. Hints, progress, prompts and errors go to stderr, so pipes get clean output.
- `cass canvas files list --json` adds `kind` (`file` or `folder`). `cass canvas modules list --json` has no items, so use `modules show --json` for those.

## Escape hatch

When no command fits, use the raw API. `{course}` expands to the course ID:

```bash
cass canvas api GET /courses/{course}/pages --all
cass canvas api GET /courses/{course}/quizzes --param 'include[]=assignment'
cass canvas api PUT /courses/{course}/modules/5 --data 'module[name]=Week 1' --dry-run
cass canvas api POST /courses/{course}/pages --json-body '{"wiki_page": {"title": "X"}}' --dry-run
```

`cass canvas api` writes don't prompt, so always `--dry-run` first. In Python, use the same client the CLI uses:

```python
from cass.apis.canvas.client import CanvasAPIError, CanvasClient
from cass.apis.canvas.dry_run import format_plan

with CanvasClient.from_config("cass.toml", dry_run=True) as c:   # or CanvasClient()
    pages = c.get_all(c.course_path("/pages"))                  # follows pagination
    c.request("PUT", c.course_path("/modules/5"), data=[("module[name]", "Week 1")])
    print("\n".join(format_plan(c.planned_requests)))           # writes recorded, not sent
```

`CanvasAPIError` has `.status_code` and `.canvas_message`. Pass repeated keys as lists of pairs.

## Canvas quirks to remember

- New `ExternalUrl` and `SubHeader` module items start unpublished.
- Canvas refuses to unpublish an item whose content can't be unpublished, such as an assignment with submissions, and answers `403 item can't be unpublished`.
- Quiz questions: positions sent at creation are ignored, and `question_count` updates only after a re-save. cass handles both. Concluded courses return 403 on the questions endpoint.
- `quizzes responses` waits about 30 seconds for Canvas's report. The Test Student is never in it.

## References

Read these when the task needs them:

- `references/quirks.md`: every verified Canvas quirk, with what cass does about it.
- `references/files-and-modules.md`: uploads, folders, duplicates, module items, declared assignments, `sync` and `--prune`.
- `references/quizzes.md`: quiz file format, question editing, previews, responses.
- `references/grades.md`: what pull removes and keeps, what push holds back, accepted grades, posting.
- `references/late-enrollments.md`: `people list --enrolled-after`, `excuse`, `clear-late`.
<!-- --8<-- [end:body] -->
