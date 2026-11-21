# 0002. Every Canvas write can be previewed

Status: Accepted

Date: 2026-10-10

## Context
An audit of about 20 agent sessions driving cass in a live course found three
write conventions: `sync` defaulted to a dry run, deletes used `--yes`, and
creates and updates had no preview. Course scripts each invented their own
preview wrapper, because agents need to show the instructor a plan before
changing a live course.

## Decision
Every command that writes to Canvas accepts `--dry-run`, which prints the exact
requests and sends nothing. Multi-step reconcile commands default to a dry run
and need `--apply`. Deletes need `--yes` and fail fast without it in a
non-interactive shell. The dry run is implemented once, in the Canvas client.

## Rationale and trade-offs
One convention lets a person or agent review every change before it reaches
students. Implementing it at the client's single request point keeps it
consistent across commands. Costs were not recorded. Source: GitHub issue #10.

## Alternatives
Per-script preview wrappers, which each course repository had reinvented.
