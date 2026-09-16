# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas) — pull rosters, track submissions, edit grades, and push them back to Canvas.

All data lives in a local SQLite database (`cass.db`) alongside a version-trackable `cass.toml` config.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Install

### Stable release (recommended)

```bash
uv tool install cassroom
```

To update:

```bash
uv tool install cassroom --upgrade
```

### From GitHub (latest)

```bash
uv tool install git+https://github.com/ejolly/cass.git
```

To update:

```bash
uv tool install git+https://github.com/ejolly/cass.git --reinstall
```

After install, `cass` is available globally.

## Get started

### Setup (one-time)

```bash
# Will ask you for canvas token and save to .canvastoken
cass init
```

#### No API token? Use your browser session instead

On macOS, log in to Canvas in Brave or Google Chrome, then run the matching command:

```bash
cass canvas login --from-brave
cass canvas login --from-chrome
```

Allow access to **Brave Safe Storage** or **Chrome Safe Storage** if macOS asks.
cass imports your Canvas cookies, checks the session, and saves `.canvascreds`
with owner-only permissions.
For another browser profile, add `--profile "Profile 1"`, using the directory name
shown in `brave://version` or `chrome://version` under **Profile Path**.

If Canvas rejects authentication, cass refreshes the cookies from that profile
and retries the request once. If the browser session has also expired, log in to
Canvas in that browser and rerun the login command. CSRF errors also point to this
command, but do not trigger an automatic retry.

For other browsers, copy `canvas_session` and `_csrf_token` from devtools
(Application/Storage > Cookies) into `.canvascreds` in the project root:

```
canvas_session=<value>
_csrf_token=<value>
```

Quotes around the values are fine. Manually copied cookies do not refresh
automatically. `.canvascreds` takes priority over `.canvastoken`; delete it to
return to API-token authentication.

### Pull latest data

```bash
cass pull
```

### Open Viewer

```bash
cass view
```

- The only tables/spreadsheets you can edit in the viewer are Canvas Gradebook & Assignments
- Just double-click a cell to edit the value like in google-sheets. Changed cells will appear in orange. 
- When you're done editing press (e.g. multiple cells) press **push** button in the top left to send updates to Canvas

### CLI

Everything you can do from the viewer you (or Claude) can do from the CLI:

```bash
cass init         # interactive config setup
cass pull         # fetch students, assignments, submissions from Canvas
cass status       # overview of local state and sync status
cass revert       # discard pending local changes
cass push         # preview + confirm pending Canvas changes
cass push --yes   # skip confirmation

# Canvas management
cass canvas                # course overview
cass canvas people         # enrolled students
cass canvas modules        # list / create / publish modules
cass canvas assignments    # list / create assignments (and groups)
cass canvas calendar       # list / create / update / delete events
cass canvas quizzes                       # list quizzes
cass canvas quizzes --id "Survey 1"       # settings + questions
cass canvas quizzes export "Survey 1" -o quizzes/survey-1.toml
cass canvas quizzes create --from quizzes/survey-1.toml [--publish] [--create-groups]
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml
cass canvas sync [--apply] [--create-groups]   # reconcile [[canvas.*]] declarations
cass canvas upload file.pdf
cass canvas announce "Title" "Body"

# Another course's config (or set CASS_CONFIG); credentials resolve beside that file
cass --config ../f25/cass.toml canvas quizzes

# Data management
# query also accepts --where, --order, and --limit
cass query students        # roster
cass query assignments     # assignment metadata
cass query submissions     # submissions dataset
cass query gradebook       # student x assignment matrix
cass query --sql "select count(*) from canvas_students"
cass backup                # timestamped snapshot → backups/
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.db
```

Running `cass` with no arguments shows help.

## Configuration

`cass.toml` lives in your project root.

```toml
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335
time_zone = "America/Los_Angeles"   # written by `cass init`; times you type are in this zone

[[canvas.quizzes]]
file = "quizzes/09-25-participation.toml"   # relative to this file; see below
```

`cass` reads times on the command line and in config files (`--due`, `--start`,
`due_at`, quiz `unlock_at`/`due_at`/`lock_at`) in the course time zone unless
they carry an explicit offset. `YYYY-MM-DD` means midnight; `YYYY-MM-DD HH:MM`
is the usual form.

### Quiz files

One TOML file per quiz. `cass canvas quizzes export` writes this format and
`create --from` reads it, so a file round-trips.

```toml
title = "09-25 Participation Survey"
type = "graded_survey"          # practice_quiz | assignment | graded_survey | survey
group = "Attendance & Participation"
points = 2                      # graded_survey only; other types sum question points
unlock_at = "2026-09-25 14:15"  # course time zone unless an offset is given
due_at = "2026-09-25 17:00"
attempts = 1                    # -1 = unlimited
hide_results = "always"         # "" | always | until_after_last_attempt

[[questions]]
type = "essay"
text = "<p>What are you most hoping to get out of this course?</p>"

[[questions]]
type = "multiple_choice"
text = "<p>Which gamble does your calculation recommend?</p>"
points = 1
answers = [{ text = "A", correct = true }, { text = "B" }]
```

- `title` and `type` are required; every other setting has a default
  (`description`, `lock_at`, `time_limit`, `scoring_policy`, `shuffle_answers`,
  `one_question_at_a_time`, `published`).
- Question `type` aliases: `essay`, `multiple_choice`, `multiple_answers`,
  `true_false`, `short_answer`, `numerical`, `text_only`. Other Canvas
  question types pass through verbatim.
- Question `points` default to 0 for surveys and 1 otherwise; `name` defaults
  to `Question N`.
- `answers` are required for `multiple_choice`, `multiple_answers`, and
  `true_false`; `correct = true` marks the right answer.
- `cass canvas sync` creates quizzes listed under `[[canvas.quizzes]]` that are
  missing on Canvas (matched by title) and updates settings that differ.
  Questions on an existing quiz are never modified.

## Development

```bash
uv sync                    # install deps
uv run poe lint            # ruff format + check, ty
uv run poe test            # pytest
uv run poe install         # install as global CLI tool
```
