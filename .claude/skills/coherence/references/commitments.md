# Commitments

`.coherence/commitments.md` is the **only binding record** in a project's coherence. It answers **"What must remain true unless the human deliberately changes the agreement?"** One kind of commitment covers behavioral promises, data preservation, architectural boundaries, and compatibility guarantees; don't subdivide them into invariants, contracts, or principles.

Every commitment is read at the start of every substantive task, so each one costs attention. Keep the list short.

## The commitment test

A candidate is a commitment only if all three are true:

1. **The human explicitly agreed** that it must hold. Project docs, `AGENTS.md`, code patterns, past decisions, and agent inference are evidence for a proposal, never acceptance.
2. **It protects something that outlives the change:** data, compatibility, an architectural boundary, or a promise to users.
3. **Breaking it is costly or hard to undo**, so it should require a deliberate human ruling rather than ordinary review.

## Commitment or convention?

Rules about *how code is written* are conventions and stay in `AGENTS.md` or style tooling. A convention violation is fixed cheaply in review. A commitment protects a property of the system. For example:

| Rule | Kind |
| --- | --- |
| "Files exported by any release must stay readable by later releases." | Commitment: compatibility |
| "HTTP handlers never query the database directly." | Ask the human: a commitment if they treat it as an architectural boundary, otherwise a convention |
| "Use f-strings for string formatting." | Convention |

Process rules that gate changes, such as "schema changes need the owner's approval" or "test against a copy first", are neither. They stay in `AGENTS.md` as process. Usually the property they protect is the commitment.

When a rule becomes a commitment, propose replacing the copy in `AGENTS.md` with a link to the commitment, so there is one authoritative copy. If only part of a rule becomes a commitment, propose the whole replacement bullet: the link plus the remaining text, unchanged. Restatements of the commitment in other docs may stay; propose links there only if the copies disagree.

## Writing a commitment

- **One obligation per commitment.** An obligation protects one property; listing several ways it could be broken is fine. Split a rule only when the human could reasonably accept one part and reject another.
- **State what must hold** using "must" or "must never", narrowly enough to settle a concrete design question.
- **State why**, so agents can reason about intent rather than only the wording.
- Add **scope or exceptions** only when omitting them would mislead.
- Optionally name an existing **check**, such as a test or command, in a code span rather than a link: links outside `.coherence/` break the site build. No commitment needs to be automatically checkable.

```markdown
## C1. Never delete recorded observations {#c1}

Recorded observations must never be deleted or overwritten, because each
one is the only record of a field measurement that cannot be repeated.
Corrections are recorded as new observations.

Check: `tests/test_store.py::test_corrections_append`
```

IDs are `C1`, `C2`, and so on, never reused. Each heading ends in an anchor matching its ID, such as `{#c1}`, so links like `commitments.md#c1` survive rewording the title.

## What does not belong

- Observations of current code ("most modules use X").
- Coding conventions and style preferences.
- Test cases, acceptance criteria, or ticket requirements.
- Aspirations that cannot settle a concrete design conflict ("the code should be clean").
- Definitions without an obligation: these are **domain**.
- Rationale and trade-offs: these are **decisions**.

## Conflicts and changes

If existing code or docs already appear to break a proposed or accepted commitment, report it with locations; don't fix it as part of recording the commitment.

If planned work conflicts with a commitment, name the commitment and explain the conflict, then ask the human for a ruling before making the conflicting change. Work that doesn't conflict can continue.

Never add, weaken, remove, reinterpret, or carve an exception into a commitment without approval of the exact new wording. When a change is approved, edit the commitment itself so the file holds only current rules; Git keeps the history. If the change reflects a consequential design choice, also propose a decision that records why. A decision alone never changes a commitment.

During review, distinguish a **demonstrated violation** from **uncertain applicability**, and cite source locations.

## File conventions

All current commitments live in `.coherence/commitments.md`, one `##` heading each. Don't add an index table, per-commitment files, or copies of the rules in `index.md`; the site's "On this page" sidebar lists the headings. Link to a commitment with `[C1](commitments.md#c1)`.
