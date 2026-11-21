---
name: coherence
description: Use when reading, proposing, or editing a project's `.coherence/` records (domain, commitments, decisions), or when deciding whether something learned during work belongs in them.
---

# Project coherence

`.coherence/` holds the small set of accepted knowledge that keeps a project conceptually consistent across changes and agent sessions. It has exactly three kinds of record:

| Record | File | Answers | Binding? |
| --- | --- | --- | --- |
| [Domain](references/domain.md) | `domain.md` | What does this project term mean? | No |
| [Commitments](references/commitments.md) | `commitments.md` | What must remain true? | **Yes, the only binding records** |
| [Decisions](references/decisions.md) | `decisions/NNNN-*.md`, indexed in `decisions.md` | Why was this hard-to-reverse choice made? | No |

Read the reference for a record type before proposing or editing an entry of that type.

## Reading

At the start of any task that may change code, data, interfaces, or project records, read `domain.md` and `commitments.md` in full. Read `decisions.md` and open individual decisions only when the area you are changing or the rationale in question is relevant.

Interpret requests, code, and documentation using the domain meanings. Check planned changes against every applicable commitment. If a change would conflict with a commitment, stop and ask the human for a ruling before making the conflicting part of the change.

## Where does it go?

Use these questions to classify a candidate, whether it is already a record or something you might propose. Ask them in order and stop at the first yes:

1. Is it something that must hold, so that breaking it should require the human's approval? → **Commitment**
2. Does it state what a project term means, with no "must" or "never"? → **Domain**
3. Does it explain why a hard-to-reverse choice was made among real alternatives? (See the [decision test](references/decisions.md#the-decision-test).) → **Decision**
4. Otherwise it is **not a coherence record**. It belongs in code, code comments, project docs, `AGENTS.md` conventions, a ticket, or nowhere.

Classifying a candidate doesn't accept it: a candidate becomes a record only through the authority rule below, and must also pass its record type's test.

Each fact has one home. When something is both a rule and a choice, the rule goes in commitments and a decision records the reasoning and links to the commitment. Link to other records instead of restating them.

## Authority: agents propose, the human accepts

Every addition, removal, or change of meaning in any record requires the human to approve its **exact wording**, item by item. This applies equally to domain terms, commitments, and decisions, however obvious the entry seems.

Agents may, without approval, make edits that change no meaning: fix broken links and anchors, typos, formatting, and decision index rows that are missing or out of date for already-accepted decision files.

Proposals, hypotheses, and review findings never go in `.coherence/`. They live in the conversation or a pull request until accepted.

## When to propose after bootstrap

Propose a new record only when the work demonstrates a need:

- **Commitment:** the human states that something must or must never happen, or corrects the same thing twice.
- **Domain:** a term was misunderstood during the task, two names turned up for one concept, or a new concept now crosses a module or interface boundary.
- **Decision:** a choice made during the task passes the decision test.

Collect proposals and present them once, at the end of the task, under the heading **Coherence proposals**. Give each one its record type, its exact text, and the evidence for it. If nothing qualifies, don't mention coherence at all.

## Red flags

| Thought | Reality |
| --- | --- |
| "Every module does X, so X is a commitment." | A pattern is not an agreement. Ask the human whether it must hold. |
| "This term is obvious, I'll just add it." | All additions are proposals. Propose it. |
| "A past decision chose X, so X is required." | Decisions explain; only commitments bind. |
| "I'll record this choice in case it matters later." | Apply the decision test. Most choices fail it. |
| "This new term is close to an existing one, but slightly different." | Extend the existing entry with a contrast, or ask the human which meaning is intended. |
| "The tests pass, so the change honors the commitments." | Passing tests are not a ruling. Check each applicable commitment. |
| "I'll put this proposal in `.coherence/` and mark it draft." | Only accepted knowledge goes in `.coherence/`. |
| "I'll tidy the wording of this commitment while I'm here." | Rewording can change meaning. Propose it. |

## Files and the site

- `domain.md` and `commitments.md`: one `##` heading per entry; no separate index tables. Commitment headings end in a stable anchor such as `{#c1}`.
- `decisions.md`: one linked row for every file in `decisions/`, sorted by ID. It is the only navigation to individual decisions.
- Use relative `.md` links between records, and update them in the same change when a heading or file is renamed.
- Never link to files outside `.coherence/`; the strict build fails on them. Cite them in a code span instead, such as `docs/architecture.md`.

After editing `.coherence/`, run `uvx zensical build -f coherence.zensical.toml` from the project root when `uvx` is available, and compare `decisions/` with the `decisions.md` table. The build fails on broken links and anchors but does not detect a missing index row. A green build checks navigation, not the correctness of any record. Preview the site with `uvx zensical serve -o -f coherence.zensical.toml`.

Use the `bootstrap` skill to adopt `.coherence/` in a project, and `review-coherence` for a deliberate diagnostic review.
