# 0003. An omitted setting leaves the live value alone

Status: Accepted

Date: 2026-10-12

## Context
An omitted `published` in `cass.toml` or a quiz file defaulted to `false`, so
`sync --apply` unpublished live modules, assignments, and quizzes, and
`quizzes update --from` reset attempts, dates, time limits, and shuffle to their
defaults.

## Decision
An omitted `published` or quiz setting means "leave as is": sync and
`quizzes update --from` compare and send only what the file sets. New content
still gets defaults (unpublished, one attempt). `quizzes update --from` became a
dry run unless `--apply`.

## Rationale and trade-offs
A declaration file describes intent, so silence must not change live content.
The accepted cost was a breaking change to `quizzes update --from`. Source:
GitHub issue #17 and commit `3f9712d`.

## Alternatives
Keeping `false` as the default, which unpublished live content.
