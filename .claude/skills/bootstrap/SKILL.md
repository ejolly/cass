---
name: bootstrap
description: Use when a project adopts `.coherence/`, to establish a small, human-approved baseline of commitments first, then only the domain terms and decisions that baseline needs or that the sources show are confused.
---

# Bootstrap project coherence

Establish a **small, trustworthy baseline** and stop. The records grow later, one demonstrated need at a time, as described in the `coherence` skill. Bootstrap does not document the project, reconstruct its history, or build a glossary.

Read the `coherence` skill and its three references first. Its classification questions, authority rule, and red flags apply throughout.

## Labelling evidence

Label every proposal with its strongest source:

- **Human (session):** the human said it in this conversation.
- **Docs:** stated in maintainer-controlled prose: docs, agent instructions such as `README.md` or `AGENTS.md`, or code comments and docstrings. Cite file and line. Docs are evidence, not acceptance, even when they use "must".
- **Inference:** derived from code, tests, history, or patterns. Cite locations.

## Stage 0: Inspect and install

1. Read `README.md`, `AGENTS.md` or equivalent agent instructions, architecture docs, and enough source, tests, and interfaces to understand the project's main boundaries. If `.coherence/` already exists, treat its records as accepted and only fill gaps.
2. Install the [project templates](../../templates/): `.coherence/` with its four pages and an empty `decisions/` directory (add a `.gitkeep` so Git keeps it), plus `coherence.zensical.toml` at the project root. Add `.coherence-site/` to `.gitignore` without discarding existing entries. Leave any existing documentation site and its config untouched, and always pass `-f coherence.zensical.toml` so Zensical doesn't pick up another config.

For a brand-new project with no agreements yet, stop after installing the empty templates. Don't invent records to fill them.

## Stage 1: Commitments

1. **Ask the human first:** "What must never break in this project, and why?" Their answer is the primary source. If they give no answer or point you to the docs, continue from the sources and label each proposal accordingly.
2. Propose **at most 5** commitments, most irreversible harm first. If there are more than 5 candidates and the human hasn't said what matters most, show the ranked list with one line of evidence each and let them choose which to draft. For each proposal, give:
   - a provisional label `P1`, `P2`, and so on; assign `C1`, `C2` in order only when writing the accepted ones, and update links to match;
   - the exact text to write, without links to domain terms, which don't exist yet;
   - its evidence label and citations;
   - any existing code or docs that already appear to break it, or "none found".
3. List further candidates on a single **Deferred** line: a short name and one citation each, without drafting them.
4. Classify the rules in `AGENTS.md` or equivalent as commitment, convention, or process, and flag any rule that contradicts another rule, the project docs, or the code and tests.
5. The human accepts, edits, or rejects each proposal. Write only the accepted ones.

## Stage 2: Domain

Propose **at most 10** terms, each meeting at least one of these:

- terms that the accepted commitments use and that need a definition to be unambiguous, and
- terms the sources show being confused or used with competing meanings.

Every term must pass the [domain test](../coherence/references/domain.md#the-domain-test) and must not overlap an existing entry or another term in the batch. If defining a term shows that an accepted commitment's wording is ambiguous, propose the reworded commitment alongside the term. Links from commitments to the new terms go in these rewordings. Write only accepted terms and rewordings.

## Stage 3: Decisions

Propose **0 to 3** decisions, and only ones that explain an accepted commitment or a major architectural boundary. Each must pass the [decision test](../coherence/references/decisions.md#the-decision-test). Recover the rationale from docs, Git history, or old discussions and cite where it lives in a code span. If the rationale can't be recovered, say so rather than writing one. If it is only partly recoverable, write only the supported parts and say what is missing. Write only accepted decisions, each with a row in `decisions.md`.

## Stage 4: Connect and stop

1. Propose adding the [standard snippet](../../templates/AGENTS-snippet.md) as its own section at the end of the project's `AGENTS.md`. Propose replacing rules that became commitments with links, as the [commitments reference](../coherence/references/commitments.md#commitment-or-convention) describes. Don't rewrite other docs.
2. When `uvx` is available, run `uvx zensical build -f coherence.zensical.toml` and fix broken links.
3. Report, in this order:
   - **Written:** the records you wrote.
   - **Deferred:** the candidates not yet proposed.
   - **Findings:** contradictions and mismatches found along the way, with locations. Don't fix them.
   - **Open questions:** anything waiting on the human.

   Then stop: further records come from later work, not from extending the bootstrap.

## Rules

- One stage at a time. Don't propose domain terms or decisions until the human has ruled on the commitments.
- The caps are ceilings, not targets. Fewer, well-evidenced records are better. A rule that doesn't fit under a cap goes on the Deferred line.
- Nothing goes in `.coherence/` until the human has accepted its exact wording.
