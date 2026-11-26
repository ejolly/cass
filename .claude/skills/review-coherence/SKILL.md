---
name: review-coherence
description: Diagnose accepted-knowledge violations and high-signal emerging conceptual inconsistencies in a project without automatically redesigning it.
---

# Review project coherence

This skill is a **deliberate diagnostic review**. Ordinary development merely reads and maintains the project records; it does not need a full review on every change.

## Read first

Read the `coherence` skill and its references for [domain](../coherence/references/domain.md), [commitments](../coherence/references/commitments.md), and [decisions](../coherence/references/decisions.md). Its classification questions and red flags apply to every finding.

Read `.coherence/domain.md` and `.coherence/commitments.md` completely. Scan `.coherence/decisions.md` and open individual decisions selectively where their rationale can clarify an apparent difference or an intentional exception. The discovery reviewer delays reading the project records until after its initial inspection, as described below.

## Independent review

When the harness supports fresh-context subagents, delegate steps 2 and 3 to two independent, read-only reviewers in parallel. Pass each the review scope, repository revision (including whether uncommitted changes are in scope), paths to this skill and its references, and neutral source locations as needed. Do not pass the conversation history, the primary agent's hypotheses, or the other reviewer's findings. Let reviewers inspect relevant sources directly and follow references beyond the initial locations when needed.

- **Conformance:** Read the accepted domain and commitments in full and scan the decision index first. Then inspect the implementation for demonstrated contradictions. Consult relevant decisions to distinguish intentional differences from drift; decisions explain but do not bind.
- **Discovery:** Inspect relevant implementation, interfaces, tests, and documentation before deliberately reading the project's coherence records. Form provisional observations about high-signal patterns and tensions, then read the domain and commitments in full, scan the decision index, and consult relevant decisions to test those observations. Differences alone are not findings. Also look for consequential implicit knowledge that a future contributor could plausibly misunderstand or inadvertently undo, even when the current implementation is consistent; apply the existing record inclusion tests before proposing additions.

Both reviewers cite source evidence, consider counterexamples, distinguish observation from inference, and report coverage limits. Neither is required to find a problem. Return findings to the primary agent; do not edit files or create separate reports.

If independent subagents are unavailable, perform the existing review directly and state that it was not independent. If a reviewer fails or returns no usable report, state the missing coverage and any direct inspection used in its place; do not count it as a clean review. If the harness automatically supplies project records or prior context, disclose the resulting limitation rather than claiming isolation or an unanchored first pass.

## Procedure

1. **Establish scope.** Identify the revision, relevant source, tests, configuration, public interfaces, documentation, and meaningful coverage limits. Keep the reviewed source state stable across reviewers. Use repository search and normal inspection tools first; optional scripts are helpers, not prerequisites. When present, run `uvx zensical build -f coherence.zensical.toml` to catch broken internal links and anchors, and compare `decisions/` with the `decisions.md` table for missing rows.
2. **Check accepted coherence.** The conformance reviewer (or the primary agent when working directly) looks for demonstrated contradictions with commitments and established domain meanings. Consider scope and known exceptions before calling a violation.
3. **Discover possible future decoherence.** The discovery reviewer (or the primary agent when working directly) looks for concrete, high-signal patterns: shared concepts represented inconsistently; related implementations acquiring conflicting semantics; intended architectural boundaries eroding; or code and documentation disagreeing.
4. **Challenge the hypothesis.** The primary agent independently verifies consequential findings against the cited sources, searches for counterexamples, and reconciles overlapping findings by their underlying conceptual tension. Apparent similarity may hide intentional differences. Use relevant decisions and counterexamples. A common implementation pattern is not automatically a binding rule, and a design difference is not inherently a defect. Contest findings with evidence; preserve material disagreement as uncertainty rather than forcing consensus. Do not dismiss a finding solely because the current conversation explains it. If a consequential explanation is unavailable in durable project sources, consider whether it reveals missing knowledge, using the existing record inclusion tests.
5. **Prioritize findings.** Present a short set of consequential observations, not a generic style critique or unsolicited full architecture redesign. Classify each as **violation**, **emerging decoherence**, or **uncertain**.
6. **Explain evidence and limits.** For each finding, provide the exact file/line or other source reference, the observed tension, why it may matter, and the unresolved interpretation. Include broken links or missing decision index rows as documentation findings, without treating them as binding commitment violations unless an actual commitment was breached. State whether review was independent and any meaningful reviewer coverage or context limitations. Do not claim that partial inspection or a successful docs build proves complete compliance.
7. **Report without rewriting.** The review is diagnostic. Do not add, revise, or remove any record, automatically remediate findings, or repeat reviews until no findings remain. Where a finding suggests a record change, include it under **Coherence proposals** with its exact text, as the `coherence` skill describes. Overlapping domain entries and decision records that fail the decision test are valid findings.

## Reporting shape

A short opening summary followed by prioritized findings. Each finding should make the **classification, evidence, impact, and uncertainty** easy to understand. State explicitly when no substantial finding was uncovered; don't equate that with a proof of coherence.

## Tool posture

Run existing project checks when relevant. Do not introduce a rule engine, formal semantics, new test harness, or required scripting runtime solely for this skill. Propose a helper only after a real, repeated manual difficulty demonstrates its value.
