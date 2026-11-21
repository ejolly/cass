---
name: review-coherence
description: Diagnose accepted-knowledge violations and high-signal emerging conceptual inconsistencies in a project without automatically redesigning it.
---

# Review project coherence

This skill is a **deliberate diagnostic review**. Ordinary development merely reads and maintains the project records; it does not need a full review on every change.

## Read first

Read the `coherence` skill and its references for [domain](../coherence/references/domain.md), [commitments](../coherence/references/commitments.md), and [decisions](../coherence/references/decisions.md). Its classification questions and red flags apply to every finding.

Read `.coherence/domain.md` and `.coherence/commitments.md` completely. Scan `.coherence/decisions.md` and open individual decisions selectively where their rationale can clarify an apparent difference or an intentional exception.

## Procedure

1. **Establish scope.** Inspect relevant source, tests, configuration, public interfaces, and documentation. Identify the revision and meaningful coverage limits. Use repository search and normal inspection tools first; optional scripts are helpers, not prerequisites. When present, run `uvx zensical build -f coherence.zensical.toml` to catch broken internal links and anchors, and compare `decisions/` with the `decisions.md` table for missing rows.
2. **Check accepted coherence.** Look for demonstrated contradictions with commitments and established domain meanings. Consider scope and known exceptions before calling a violation.
3. **Discover possible future decoherence.** Look for concrete, high-signal patterns: shared concepts represented inconsistently; related implementations acquiring conflicting semantics; intended architectural boundaries eroding; or code and documentation disagreeing.
4. **Challenge the hypothesis.** Apparent similarity may hide intentional differences. Use relevant decisions and counterexamples. A common implementation pattern is not automatically a binding rule, and a design difference is not inherently a defect.
5. **Prioritize findings.** Present a short set of consequential observations, not a generic style critique or unsolicited full architecture redesign. Classify each as **violation**, **emerging decoherence**, or **uncertain**.
6. **Explain evidence and limits.** For each finding, provide the exact file/line or other source reference, the observed tension, why it may matter, and the unresolved interpretation. Include broken links or missing decision index rows as documentation findings, without treating them as binding commitment violations unless an actual commitment was breached. Do not claim that partial inspection or a successful docs build proves complete compliance.
7. **Report without rewriting.** The review is diagnostic. Do not add, revise, or remove any record. Where a finding suggests a record change, include it under **Coherence proposals** with its exact text, as the `coherence` skill describes. Overlapping domain entries and decision records that fail the decision test are valid findings.

## Reporting shape

A short opening summary followed by prioritized findings. Each finding should make the **classification, evidence, impact, and uncertainty** easy to understand. State explicitly when no substantial finding was uncovered; don't equate that with a proof of coherence.

## Tool posture

Run existing project checks when relevant. Do not introduce a rule engine, formal semantics, new test harness, or required scripting runtime solely for this skill. Propose a helper only after a real, repeated manual difficulty demonstrates its value.
