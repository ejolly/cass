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
3. On an error, rerun with `cass --debug …` for the traceback. Exit 1 means the command failed. Exit 2 means a usage error.

## Safety rules

- **Dry run every write first.** Every Canvas write takes `--dry-run`, which prints the exact requests and sends none. The one exception is `cass canvas quizzes preview`, which leaves a teacher preview attempt on Canvas. Reconcile commands are dry runs unless you pass `--apply`: `cass canvas sync`, `cass canvas quizzes update QUIZ --from FILE --questions`, `cass canvas submissions excuse` and `cass canvas submissions clear-late`.
- **Show the plan and wait.** Paste the dry-run output to the user. Run the real command, or add `--apply`, only after they agree.
- **Deletes need `--yes`.** You have no TTY, so a prompting command exits 1 without it. Pass `--yes` only after the user approved that dry run.
- **Never publish unless asked.** Don't pass `--publish` or run `publish` verbs unless the user asked. `cass canvas files upload` makes the file visible to students unless you pass `--unpublished`, so pass it by default. Announcements and calendar events are visible to students as soon as they're created; there is no unpublished state.
- **Never unpublish by accident.** A module, assignment or quiz that `cass.toml` or a quiz file declares without `published` counts as `published = false`. `sync --apply` or `quizzes update --from` then unpublishes it if it's live and published. Content the file doesn't declare is never touched. Set `published` to the current live value (check `cass canvas modules list --json` or `cass canvas quizzes show QUIZ --json`) and change it only when asked.
- **`quizzes update --from` without `--questions` has no `--apply` gate.** It sends at once and resets every quiz setting the file leaves out to its default. Start from `cass canvas quizzes export QUIZ -o FILE`, which writes every setting with its live value, and run with `--dry-run` first.
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
| Readings and files | `cass canvas files upload notes.pdf --folder readings/week1 --unpublished --dry-run` |
| File tree, folders | `cass canvas files list --json`; `cass canvas files folders list` |
| Move, rename, hide or show a file | `cass canvas files mv`, `rename`, `unpublish`, `publish` |
| Create a quiz or survey | write a quiz file, then `cass canvas quizzes create --from quizzes/survey.toml --dry-run` |
| Edit quiz settings | `cass canvas quizzes update QUIZ --from FILE --dry-run` |
| Edit quiz questions | `cass canvas quizzes export QUIZ -o FILE`, edit it, then `cass canvas quizzes update QUIZ --from FILE --questions` |
| See question IDs and groups, or a student's view | `cass canvas quizzes questions QUIZ --json`; `cass canvas quizzes preview QUIZ` |
| Pull survey or quiz answers | `cass canvas quizzes responses QUIZ --csv responses.csv` |
| Submissions and scores | `cass canvas submissions list HW1 --json` |
| Late-enrolled students | `cass canvas submissions excuse --enrolled-after DATE`; `cass canvas submissions clear-late --enrolled-after DATE` |
| Assignments, groups | `cass canvas assignments create "HW 3" --group Labs --due "2026-10-20 23:59" --dry-run` |
| Announcements | `cass canvas announcements create "Title" -m "<p>Body</p>" --dry-run` |
| Calendar | `cass canvas calendar create "Review" --start "2026-10-20 10:00" --dry-run` |
| Navigation tabs | `cass canvas tabs list`; `cass canvas tabs hide Grades --dry-run` |
| Read grades | `cass pull`, then `cass query submissions --where "score < 50"`; `cass query gradebook` for the student × assignment matrix |
| Push grade edits made in `cass view` | `cass push --dry-run`, then `cass push --yes` |
| Anything else | `cass canvas api` (see below) |

Commands take an ID or a name, and an ambiguous name fails and lists the matching IDs. Calendar events take IDs only. Times are course-local (`YYYY-MM-DD HH:MM`) unless they carry an offset.

## Output

- `--json` prints JSON Lines on `list` commands and a single object on `show` and `cass status --json`, using Canvas field names. It can't be combined with `--csv` or `--save`.
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
- `references/files-and-modules.md`: uploads, folders, duplicates, module items, `sync` and `--prune`.
- `references/quizzes.md`: quiz file format, question editing, previews, responses.
- `references/late-enrollments.md`: `people list --enrolled-after`, `excuse`, `clear-late`.
<!-- --8<-- [end:body] -->
