# Decisions

Complete index of accepted consequential design choices. Each file under `decisions/` must have exactly one linked row, sorted by stable decision ID. This table is the only navigation to individual decisions; the records themselves carry the reasoning and trade-offs. Dates unknown from source evidence can be marked `—`. Superseded decisions stay indexed, and their summary names the replacement. See the coherence skill's `references/decisions.md` for what qualifies as a decision.

| ID | Decision | Date | Summary |
| --- | --- | --- | --- |
| 0001 | [Pending changes are a diff against the last pull](decisions/0001-pending-changes-as-shadow-diff.md) | 2026-03-06 | Shadow tables record what Canvas had at the last pull. |
| 0002 | [Every Canvas write can be previewed](decisions/0002-dry-run-on-every-write.md) | 2026-10-10 | `--dry-run` everywhere, `--apply` for reconcile, `--yes` for deletes. |
| 0003 | [An omitted setting leaves the live value alone](decisions/0003-omitted-settings-leave-live-values.md) | 2026-10-12 | Declaration files send only what they set. |
| 0004 | [A grade with an unknown baseline is kept as a conflict](decisions/0004-unknown-grade-baselines.md) | 2026-11-23 | Non-blank local grades are kept and need approval; blank ones take Canvas's value. |
