# Domain

Shared meanings of important project concepts. Record only concepts whose ambiguity could make future development inconsistent; do not add unaccepted concepts.

Give each concept its own `##` heading. The site's "On this page" sidebar lists them, so no separate index is needed. See the coherence skill's `references/domain.md` for what belongs here.

## Quiz

A Canvas Classic Quiz, including graded and ungraded surveys. cass does not
support New Quizzes, which use a different Canvas API, so every cass rule about
quizzes refers to Classic Quizzes only.

## Finished attempt

A student's quiz attempt that Canvas has closed, in state `complete` or
`pending_review` (an attempt awaiting manual grading of essay questions).
Distinct from an attempt still in progress, a teacher's preview attempt, and an
attempt by the Test Student, none of which count as finished attempts.

## Student

A person with a student enrollment in the course whose enrollment is active or
invited. Distinct from the Test Student, which Canvas creates for previews and
leaves out of quiz reports, and from people whose enrollment is concluded or
inactive.

## Grade

The value Canvas records as a student's result on an assignment, as entered: a
number of points, a percentage, a letter, or complete/incomplete. Distinct from
the score, the number of points Canvas computes from the grade.

## Pending change

A local grade or assignment field in `cass.db` that differs from the value
Canvas had at the last pull, or a non-blank grade whose value at the last pull
is unknown ([0004](decisions/0004-unknown-grade-baselines.md)). Pending changes
survive restarts and block the next pull. They end when pushed, reverted, edited
back to the last pulled value, or deleted with their assignment.

## Visible to students

Content a student can open or see in the course: a published module,
assignment, quiz, or page; an unlocked file; and any announcement or calendar
event, which have no unpublished state. For a file, a module item's `published`
setting controls the file's lock, not the item.

A grade is visible once Canvas has posted it to the student; on an assignment
with a manual posting policy, entering a grade does not post it.

## Module

A named, ordered section of the course that students work through, holding
module items. A module item only points at content: an assignment, quiz, page,
file, external URL, or a subheader that labels a group of items. Removing an
item leaves the content it points at untouched.

## File

A document stored in the course's Files area, named by its path below the
course files root, such as `readings/week1/intro.pdf`. Distinct from a module
item that links to it, and from a local source file in the course directory
that cass uploads. Uploading over an existing file creates a new file with a new
ID, and Canvas re-points links to it.

## Announcement

A post to the whole course, which students can see as soon as it is created and
may be notified about immediately. It has no unpublished state, so creating one
cannot be previewed on Canvas. Distinct from a calendar event and from a page.
