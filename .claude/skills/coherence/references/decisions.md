# Decisions

A decision record preserves **why a consequential design choice was made**, so future contributors don't reopen a settled debate or accidentally undo an intentional trade-off. It answers **"Why did we choose this approach?"** It is reasoning, **not a binding rule**: if the choice creates something future changes must preserve, that is a separate commitment.

## The decision test

Record a choice only if all three are true:

1. **A real alternative existed.** Another approach was considered, or would plausibly be proposed by a competent newcomer.
2. **Reversing it is expensive.** It would touch persisted data, a public interface, or several components.
3. **Someone could plausibly reopen or reverse it without knowing why it was made.**

The reasoning may already exist in docs, comments, or commit history; that doesn't disqualify a decision. The record makes the choice findable from the index. Keep it short and cite the existing docs in a code span, such as `docs/architecture.md`, rather than copying them. Links outside `.coherence/` break the site build.

If the choice matters only to the change that made it, a commit message is enough: it is not a decision.

| Usually a decision | Usually not a decision |
| --- | --- |
| Representation boundaries (one model shared by all device vendors) | Library choice inside one module |
| Storage, schema-evolution, or compatibility strategy | Naming, file layout, refactor approach |
| How the system is decomposed into components | How a bug was fixed |
| A public interface or data format | Parameter values, thresholds, tuning |
| | Each step of a plan, or one record per PR |

## Writing a decision

Use one file per decision: `.coherence/decisions/0001-short-title.md`, `0002-...`, with stable, increasing, never-reused IDs.

```markdown
# 0001. Device-neutral observation model

Status: Accepted

Date: 2026-11-18

## Context
The problem or competing priorities that required a choice.

## Decision
What was agreed.

## Rationale and trade-offs
Why this approach, including the costs knowingly accepted.

## Alternatives
Other approaches that were actually considered.
```

- `Status` is exactly `Accepted` or `Superseded by [NNNN](NNNN-title.md)`.
- `Date` is the date the choice was made, or `—` when sources don't show it. Never invent a date.
- Write only the sections the sources support. If the benefits are recorded but the costs are not, say so in the proposal rather than inventing trade-offs.
- Omit **Alternatives** if none were actually considered. Never invent alternatives or rationale; if the reason can't be recovered from sources or the human, say so in the proposal.
- Link to commitments and domain terms the decision relates to, e.g. `[C1](../commitments.md#c1)`, rather than restating them.

## What does not belong

- Tickets, plans, progress logs, or changelogs of *what* changed.
- Mandatory rules: these are **commitments**.
- Unresolved options or guessed historical intent.
- Copies of architecture documentation maintained elsewhere; cite it instead.

## Superseding

Never rewrite an accepted decision to describe a new choice. To revise one, propose a new decision that explains what changed, then set the old record's `Status` to `Superseded by` the new one and note it in the old row's index summary. If the revision affects a commitment, propose that change separately; a decision alone never changes a commitment.

## Using decisions

- Read the index, then open only decisions relevant to the area you are changing.
- When work would reverse a recorded decision, explain the original reasoning and what has changed, and ask the human before proceeding.
- During review, use decisions to tell an intentional difference from an accidental one, never to infer a binding rule.

## The index

`.coherence/decisions.md` holds one linked row for every decision file, sorted by ID. It is the site's only navigation to individual decisions, so a decision missing from the index is effectively invisible.

```markdown
| ID | Decision | Date | Summary |
| --- | --- | --- | --- |
| 0001 | [Device-neutral observation model](decisions/0001-device-neutral-observation-model.md) | 2026-11-18 | Vendor differences stay at import boundaries. |
```

The summary distinguishes the choice rather than repeating the title. Update the index in the same change that adds, renames, or supersedes a decision.
