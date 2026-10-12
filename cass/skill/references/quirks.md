# Canvas quirks

Canvas behaviors that `--help` won't tell you. Each one is documented in the cass guides or code. "cass handles it" means you only need it when you go through `cass canvas api` or Python.

## Publishing and visibility

- `cass canvas files upload` leaves the file visible to students, which is Canvas's default for uploads. `--unpublished` locks it with a second request right after the upload. Pass `--unpublished` unless the user asked to publish.
- A `sync` File item works the other way. A new upload stays locked unless the item declares `published = true`. An overwrite with `published` omitted keeps the file's current lock.
- A `[[canvas.modules]]` or `[[canvas.assignments]]` entry, module item or quiz file without `published` leaves the live state as it is. `sync` creates missing modules, assignments and quizzes unpublished.
- cass never compares or sends a setting the quiz file leaves out. A new quiz gets 1 attempt, `keep_highest`, no time limit, no shuffle, all questions on one page, and stays unpublished. An empty string (`due_at = ""`) or `time_limit = 0` clears the live value.
- New `ExternalUrl` and `SubHeader` module items start unpublished. Other new items take their content's published state.
- An Assignment, Quiz or Page item's `published` also publishes or unpublishes the content itself. If it disagrees with the assignment's `[[canvas.assignments]] published`, each `sync` flips it back and forth, so declare one value in both places.
- Canvas answers an item unpublish with `403 item can't be unpublished` when its content can't be unpublished, such as an assignment with submissions or the front page. Canvas checks even when the item is already unpublished. cass sends `published` only when it differs, but a declared `false` on such an item fails every `--apply`. Leave `published` out.

## Files

- An overwrite upload, which is the `--on-duplicate` default, makes a new file with a new ID. Canvas deletes the old file and re-points module items and course links to the new one, so a file ID you saved earlier goes stale.
- `--on-duplicate skip` skips only on the same name and size. The same name with a different size is overwritten.
- `files mv` and `files rename` fail in Canvas on a name clash unless you pass `--on-duplicate rename` or `--on-duplicate overwrite`.
- Folder paths are relative to the course files root. Write `readings/w1`, not `course files/readings/w1`.

## Modules

- The module list's `include[]=items` silently leaves `items` out of modules with many items. cass reads items per module, and so should you: `cass canvas modules show "Week 1" --json`.

## Classic quizzes

- Canvas reports every question's `position` as null. The quiz order is the order Canvas lists the questions in, together with each group's position.
- Canvas ignores the positions you send when it creates questions. `quizzes update --questions --apply` reorders the whole quiz whenever it changes anything. `quizzes create --from` reorders only when the file declares groups.
- `question_count` and `points_possible` change only when the quiz is re-saved. cass re-saves after every question change. After a raw API edit, re-save it yourself: `cass canvas api PUT /courses/{course}/quizzes/ID --data 'quiz[notify_of_update]=false'`.
- When a question update leaves a field out, Canvas refills it from a copy saved at creation, which can undo earlier edits. cass resends text, name, type, points, answers and feedback on every update. Raw updates must do the same.
- Updating a question with `quiz_group_id: null` leaves it in its group. Only reordering the quiz takes it out. Deleting a group deletes the questions in it.
- An answer sent without an ID gets a new one, and a new ID can unlink earlier student responses. cass reuses the IDs of answers whose text is unchanged.
- In concluded courses, the questions endpoint returns 403. `quizzes show`, `questions` and `export` fall back to `/statistics`, which has no names or answer weights. `quizzes show`, `questions` and `export` warn about it on stderr, and `quizzes show --json` also sets `questions_source` to `statistics`. `quizzes update --questions` refuses such quizzes. `quizzes responses` still works, because it uses the report.
- Canvas wraps question text in theme CSS and JS unless you ask for the stored HTML. cass asks for it.

## Quiz responses and attempts

- `quizzes responses` asks Canvas to generate a student analysis report and waits for it, which takes about 30 seconds.
- Canvas leaves the Test Student out of quiz reports and statistics.
- An attempt with essay questions ends in `pending_review`, not `complete`. Count both as finished.
- When a course concludes, Canvas force-submits attempts that were opened but never submitted, and stamps them with the term end date. `auto_submitted` in the responses CSV flags these, but it also flags attempts that ran out of time, which hold real answers. An auto-submitted attempt stamped at the term end is the conclusion case. Don't read those as submissions made on that date.
- `started_at` and `auto_submitted` cover only each student's latest attempt.

## Enrollments and submissions

- Canvas fills in a new student's due dates a few moments after they enroll, so `--enrolled-after` may miss a student added minutes ago.
- When a student resubmits, Canvas resets the late status, so a late resubmission is late again. If they resubmitted after grading, the deduction stays until the submission is regraded.
- Setting a late status on an excused submission un-excuses it, and on a group-graded assignment it changes every group member. `clear-late` skips both.
- Excusing clears the grade.
