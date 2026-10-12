# Quizzes and surveys

These commands cover Classic Quizzes only. New Quizzes use a different API, and cass doesn't support them.

## Commands

```bash
cass canvas quizzes list --json
cass canvas quizzes show "Survey 1" --json           # settings plus questions
cass canvas quizzes questions "Survey 1" --json      # question IDs, types, groups, in quiz order
cass canvas quizzes preview "Survey 1"               # one student-style draw; the preview stays on Canvas
cass canvas quizzes export "Survey 1" -o quizzes/survey-1.toml
cass canvas quizzes create --from quizzes/survey-1.toml --dry-run
cass canvas quizzes create --from quizzes/survey-1.toml --create-groups --dry-run   # missing assignment group
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml               # settings plan, sends nothing
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml --apply
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml --questions     # settings and question plan
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml --questions --apply
cass canvas quizzes delete "Survey 1" --dry-run
```

`create` without `--from` makes an empty placeholder from flags such as `--type`, `--due`, `--unlock`, `--lock`, `--attempts` and `--group`. Use a quiz file whenever the quiz needs questions. cass can add questions and set dates. Don't tell the user it can't.

## Quiz file

```toml
title = "09-25 Participation Survey"
type = "graded_survey"          # practice_quiz | assignment | graded_survey | survey
group = "Attendance & Participation"   # assignment group
points = 2                      # graded_survey only
unlock_at = "2026-09-25 14:15"  # course time zone unless an offset is given
due_at = "2026-09-25 17:00"
attempts = 1                    # -1 = unlimited
published = false               # omit to leave the live quiz as it is

[[questions]]
type = "essay"
text = "<p>What are you hoping to get out of this course?</p>"

[[questions]]
type = "multiple_choice"
text = "<p>Which gamble do you choose?</p>"
points = 1
answers = [{ text = "A", correct = true }, { text = "B" }]
```

- `title` and `type` are required. Other settings are `description`, `lock_at`, `time_limit`, `hide_results`, `scoring_policy`, `shuffle_answers` and `one_question_at_a_time`. `update` and `sync` compare and send only the settings the file sets, so a file with only the settings to change is enough.
- Question types: `essay`, `multiple_choice`, `multiple_answers`, `true_false`, `short_answer`, `numerical` and `text_only`. Other Canvas type names pass through.
- Question `points` default to 0 on surveys and 1 elsewhere. `answers` are required for choice and true/false questions.
- Question groups draw `pick_count` questions from a pool on each attempt. Declare `[[groups]]` with `name`, `pick_count` and `points_per_item`, and set `group = "Pool"` on each question in it. Grouped questions must sit next to each other. Inside `[[questions]]`, `group` names a question group. At the top level, it names the assignment group.
- To link a quiz to `sync`, add `[[canvas.quizzes]] file = "quizzes/x.toml"` to cass.toml. `sync` creates missing quizzes and updates their settings, but never their questions.

## Editing questions

1. Run `cass canvas quizzes export QUIZ -o FILE`. The export carries question IDs (answers are matched by text) and every setting with its live value, `published` included.
2. Edit FILE. Reordering the questions reorders the quiz.
3. Run `cass canvas quizzes update QUIZ --from FILE --questions`. It prints a `keep`, `add`, `update`, `delete` or `extra` line for each question and group. Show the plan to the user.
4. Add `--apply` once they agree. Add `--prune` only to delete the `extra` questions and groups the file doesn't have.

- Matching goes by `id`, then by a unique name, then by order. `Question` and `Question N` count as no name.
- cass edits only essay, text-only, multiple-choice, multiple-answers, true/false and short-answer questions. If any other type would change, the plan errors. Keep those questions unchanged in the file, or edit them in Canvas.
- If students have finished attempts, cass warns. Earlier attempts keep the old question version. Plan lines are flagged when an answer is reworded or removed, because that gets a new answer ID and can unlink earlier responses. Changing only which answer is correct is safe.
- `--apply` sends the changed settings first, then the questions in a fixed order, then re-saves the quiz. It stops at the first failure and lists the steps that finished.
- Quizzes in concluded courses are refused, because Canvas serves their questions only through statistics.

## Responses

```bash
cass canvas quizzes responses "Survey 1" --csv responses.csv                  # latest attempt per student
cass canvas quizzes responses "Survey 1" --all-attempts --csv responses.csv
cass canvas quizzes responses "Survey 1" --wide --csv report.csv              # Canvas's report unchanged
```

- The report takes about 30 seconds, and it works on concluded courses. `cass pull --submissions` syncs scores only, not answers.
- The long CSV has one row per student, attempt and question, with the columns `student`, `user_id`, `sis_id`, `section`, `attempt`, `submitted_at`, `due_at` (the student's own), `late`, `started_at`, `auto_submitted`, `question_id`, `position`, `question`, `answer` and `score`. Times are ISO 8601 in course time.
- `auto_submitted = true` means Canvas closed the attempt itself: a time limit ran out, or the course concluded on an attempt the student never submitted. The flag alone doesn't tell them apart. A timed-out attempt holds real answers; keep it. An attempt stamped at the term end is the conclusion case and is not a real submission.
- The Test Student never appears. Calculated questions don't show the randomized values the student saw.
