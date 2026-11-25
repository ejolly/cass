# 0006. Push releases grades only with separate approval

Status: Accepted

Date: 2026-11-23

## Decision
On an assignment that posts manually, push releases a grade only when the user
approved releasing it, separately from approving the push, and only for students
whose pushed grade Canvas shows as sent. `--yes` is not that approval. Pushing
to an assignment that posts automatically, or changing a grade already released,
needs no separate approval; cass counts the latter before the push.
