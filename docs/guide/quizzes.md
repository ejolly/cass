# Quizzes

Author Canvas quizzes as TOML files in your course directory, then create, update, and sync them from the command line. `export` writes the format and `create --from` reads it, so a file round-trips.

## Commands

```bash
cass canvas quizzes list
cass canvas quizzes show "Survey 1"                   # settings and questions (--json for machines)
cass canvas quizzes export "Survey 1" -o quizzes/survey-1.toml
cass canvas quizzes create --from quizzes/survey-1.toml [--publish] [--create-groups]
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml [--questions [--apply] [--prune]]
cass canvas quizzes questions "Survey 1"              # question IDs, groups, types (--json for machines)
cass canvas quizzes preview "Survey 1"                # one student-style draw of the questions
cass canvas quizzes publish "Survey 1"                # also unpublish, delete
cass canvas quizzes responses "Survey 1" [--all-attempts] [--csv responses.csv] [--wide]
cass canvas sync [--apply] [--create-groups]          # reconcile [[canvas.quizzes]] declarations
```

`sync` and plain `update` change quiz settings only. `update --questions` also changes questions; see [Editing questions](#editing-questions).

## Quiz file

One TOML file per quiz.

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

- `title` and `type` are required; every other setting has a default (`description`, `lock_at`, `time_limit`, `scoring_policy`, `shuffle_answers`, `one_question_at_a_time`, `published`).
- Question `type` aliases: `essay`, `multiple_choice`, `multiple_answers`, `true_false`, `short_answer`, `numerical`, `text_only`. Other Canvas question types pass through verbatim.
- Question `points` default to 0 for surveys and 1 otherwise; `name` defaults to `Question`.
- `answers` are required for `multiple_choice`, `multiple_answers`, and `true_false`; `correct = true` marks the right answer.

## Editing questions

`export` writes the questions with their Canvas IDs. Edit the file, then send it back:

```bash
cass canvas quizzes export "Survey 1" -o quizzes/survey-1.toml
# edit the file
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml --questions           # dry run: shows the plan
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml --questions --apply   # send it
```

Without `--apply`, `--questions` sends nothing and prints one line per question and group (`keep`, `add`, `update`, `delete`, `extra`). A question on Canvas but not in the file is `extra` and stays untouched. `--prune` deletes those questions instead, along with any group missing from the file.

cass matches each file question to a Canvas question by `id`, then by name if the name is unique, then by relative order among the rest. A question with no `id` (a new one) matches by name or order, or is added. Reordering the file reorders the quiz. `Question` and `Question N` count as no name, and cass posts an unnamed new question as `Question`.

A question group makes Canvas draw a few questions from a pool for each attempt:

```toml
[[groups]]
name = "Pool"
pick_count = 1         # default 1
points_per_item = 2    # default: the quiz type's question points

[[questions]]
group = "Pool"         # a question group, not the quiz's assignment `group`
text = "<p>First candidate</p>"

[[questions]]
group = "Pool"
text = "<p>Second candidate</p>"
```

Questions in one group must be next to each other. The group takes the place of its first question in the quiz.

`update --questions --apply` sends settings changes first, including `published`, so a file with `published = true` publishes the quiz before its questions change. It then runs these steps in order: create new groups, add, update and delete questions, update groups, reorder the quiz and each group, delete groups, and re-save the quiz. If a request fails, cass stops. The settings stay applied, and the error lists the steps that finished before the failure.

`update --questions` refuses quizzes in concluded courses. Canvas serves their questions only through quiz statistics, which lack names and answer weights. `questions` and `export` still work there, with a warning.

If students have finished attempts, cass warns first, because Canvas keeps earlier attempts on the old version of each question. Plan lines for questions whose answers change are marked, because a new or reworded answer gets a new answer ID, which can unlink earlier responses.

`questions` lists a quiz's questions in order, with IDs and groups. `preview` starts a teacher preview and lists the questions in the order a student would see them. Groups and shuffling make each attempt differ. Canvas shows students `Question N` instead of question names, so the preview does too. The preview submission stays on Canvas.

### Canvas quirks

- The questions API reports every question's `position` as null, so cass reads the quiz order from the order Canvas lists questions in and from each group's position.
- Positions sent when creating questions are ignored. `update --questions --apply` reorders the quiz whenever it changes anything, which keeps positions exact. A quiz edited in Canvas after deleting questions may read slightly out of order until the next apply. `create --from` reorders the new quiz only when the file declares groups.
- Canvas fills any field a question update leaves out from a copy saved when the question was created, so a partial update would undo earlier edits. cass sends the whole question on every update.
- Unless asked for the stored HTML, Canvas wraps question text in the account's theme CSS and JS and rewrites file links. cass reads the stored HTML, so exported text matches what was sent.
- Canvas recounts `question_count` only when the quiz is re-saved, so cass re-saves after sending changes.
- Updating a question with `quiz_group_id: null` leaves it in its group; only reordering the quiz takes it out.
- Deleting a group deletes its questions. cass first moves the questions the file keeps out of the group, and deletes groups last.
- An answer sent without an ID gets a new one. cass reuses the ID of a live answer with the same text, so only new or reworded answers get new IDs.

## Declaring quizzes in cass.toml

```toml
[[canvas.quizzes]]
file = "quizzes/09-25-participation.toml"   # relative to cass.toml
```

`cass canvas sync` creates quizzes listed here that are missing on Canvas (matched by title) and updates settings that differ.

## Downloading responses

`cass canvas quizzes responses` downloads every student's answers to a classic quiz or survey. `cass pull --submissions` syncs scores only; use this when you need the answers themselves, for example to analyze a survey.

```bash
cass canvas quizzes responses "Survey 1" --csv responses.csv                  # latest attempt per student
cass canvas quizzes responses "Survey 1" --all-attempts --csv responses.csv   # every attempt
cass canvas quizzes responses "Survey 1" --wide --csv report.csv              # Canvas's report, unchanged
```

cass asks Canvas to generate a student analysis report and waits for it, which usually takes about 30 seconds. This also works on concluded courses, where the quiz questions endpoint returns 403.

The CSV has one row per student, attempt, and question. Times are ISO 8601 in the course time zone, with its offset (`2026-09-25T16:30:00-07:00`).

| Column | Meaning |
| --- | --- |
| `student`, `user_id`, `sis_id`, `section` | Who answered |
| `attempt` | Attempt number, blank if it can't be determined |
| `submitted_at` | When the attempt was submitted |
| `due_at` | The student's own due date, including overrides and extensions; the quiz due date if the quiz has no assignment |
| `late` | `submitted_at` is after `due_at` |
| `started_at` | When the student opened the attempt (latest attempt only) |
| `auto_submitted` | Canvas closed the attempt itself (latest attempt only) |
| `question_id`, `position`, `question` | The question, in report order; `question` is the report's text |
| `answer`, `score` | The student's answer, trimmed of surrounding whitespace, and the points it earned |

`auto_submitted` is `true` when an attempt finished at or after its cutoff. This happens when a time limit runs out, and when a student opened an attempt but never submitted it: Canvas force-submits those when the course concludes and stamps them with the term end date. Without this flag, those attempts look like real submissions made on that date.

Limitations:

- Classic Quizzes only. New Quizzes use a different reporting API.
- Calculated (formula) questions show the student's answer but not the randomized values they saw.
- `started_at` and `auto_submitted` are blank for earlier attempts. Canvas keeps timing only for each student's latest attempt, so they are also blank when a student has opened a newer attempt without submitting it.
