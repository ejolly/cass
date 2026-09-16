# Quizzes

Author Canvas quizzes as TOML files in your course directory, then create, update, and sync them from the command line. `export` writes the format and `create --from` reads it, so a file round-trips.

## Commands

```bash
cass canvas quizzes                                  # list quizzes
cass canvas quizzes --id "Survey 1"                  # settings and questions
cass canvas quizzes export "Survey 1" -o quizzes/survey-1.toml
cass canvas quizzes create --from quizzes/survey-1.toml [--publish] [--create-groups]
cass canvas quizzes update "Survey 1" --from quizzes/survey-1.toml
cass canvas quizzes publish "Survey 1"               # also unpublish, delete
cass canvas sync [--apply] [--create-groups]         # reconcile [[canvas.quizzes]] declarations
```

`update` and `sync` change quiz settings only. Questions on an existing quiz are never modified.

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
- Question `points` default to 0 for surveys and 1 otherwise; `name` defaults to `Question N`.
- `answers` are required for `multiple_choice`, `multiple_answers`, and `true_false`; `correct = true` marks the right answer.

## Declaring quizzes in cass.toml

```toml
[[canvas.quizzes]]
file = "quizzes/09-25-participation.toml"   # relative to cass.toml
```

`cass canvas sync` creates quizzes listed here that are missing on Canvas (matched by title) and updates settings that differ.
