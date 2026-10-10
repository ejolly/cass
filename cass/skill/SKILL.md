---
name: cass
description: Drive Canvas LMS from the terminal with the cass CLI. Use for any Canvas course task.
---

# cass

Placeholder; the full skill lands in the next commit.

```bash
cass status
cass --config other/cass.toml status
cass pull
cass push --dry-run
cass query students
cass canvas people list --json
cass canvas modules list --json
cass canvas modules show "Week 1"
cass canvas assignments list --json
cass canvas quizzes list --json
cass canvas quizzes create --from quizzes/survey.toml --dry-run
cass canvas quizzes responses "Survey 1" --csv responses.csv
cass canvas files list
cass canvas files upload notes.pdf --folder readings --dry-run
cass canvas sync
cass canvas api GET /courses/{course}/modules --all
cass skill install
```
