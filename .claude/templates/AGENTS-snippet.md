## Project coherence

This project keeps accepted conceptual knowledge in `.coherence/`: the meanings of domain terms, binding commitments, and the rationale for consequential decisions. Follow the `coherence` skill whenever you read, propose, or edit these records.

- At the start of any task that may change code, data, interfaces, or project records, read `.coherence/domain.md` and `.coherence/commitments.md`. Open decisions from `.coherence/decisions.md` only when they are relevant.
- Commitments are the only binding project agreements. If a change would conflict with one, stop and ask for a ruling.
- Agents propose; the human accepts. Never add, remove, or change the meaning of any record without the human approving its exact wording. Fixing links, typos, and formatting is fine.
- Collect any proposals and present them once, at the end of the task, under **Coherence proposals**.

To view the records as a site, run `uvx zensical serve -o -f coherence.zensical.toml`. After editing `.coherence/`, check links with `uvx zensical build -f coherence.zensical.toml`.
