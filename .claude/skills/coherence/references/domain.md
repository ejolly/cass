# Domain

`.coherence/domain.md` defines the **shared meaning of project concepts**. It stops people and agents from using one word for different things, or different words for one thing, without noticing. An entry answers **"What is this concept in this project?"**, not "How must it be implemented?"

There is no limit on the number of entries, but every entry must earn its place and must not overlap another. A sprawling or overlapping glossary harms coherence more than a missing term.

## The domain test

Add a term only if both are true:

1. **Its meaning is specific to this project.** The project uses it in a way that a general definition, the code, or common technical usage would not tell a newcomer.
2. **It needs to be shared.** It appears at a public interface (CLI, API, schema, data files, user docs), **or** it has a confusable neighbor: a similar term, a homonym, or an ordinary meaning that differs from the project meaning.

Generic technical terms (cache, API, migration) fail the test unless the project gives them a special meaning.

## Avoiding overlap

Before proposing a term, check it against every existing entry and every other term in the same batch of proposals:

- **Same concept, different name?** Propose using the existing name. Don't add a synonym entry.
- **Does it differ from an existing entry by a single trait, with no name of its own at a public interface?** Mention it as a contrast in that entry instead of adding a new one. Otherwise give it its own entry, even if its definition refers to other terms.
- **Does it partly overlap an existing entry?** Ask the human where the boundary lies before proposing either definition.

Two entries must never describe the same thing. If you notice that two existing entries overlap, report it and ask the human how to resolve it.

## Writing an entry

One concept per `##` heading, using the project's canonical name for it. The definition is a short paragraph that states:

- **what kind of thing it is**, and
- **what distinguishes it**, including the contrast with its nearest confusable neighbor.

```markdown
## Observation

One field measurement in the device-neutral form the project stores and
analyzes: what was measured, where, when, and by which device. Distinct from
a device upload, which is a vendor's original file and an input format rather
than the project's model.
```

Keep obligations out. If a definition needs "must" or "never", the obligation is a separate commitment candidate. Keep implementation detail out: no class names, columns, or commands unless the concept is the name itself. When an identifier is confusing (one table name meaning two things, or one word used for several fields), define the underlying concepts and mention the identifier only to resolve the confusion.

## What does not belong

- Classes, functions, columns, commands, or other implementation detail.
- Obligations: these are **commitments**.
- Why a design was chosen: this is a **decision**.
- Meanings the human hasn't accepted. Every new or inferred definition is a proposal: present it for approval and never write it directly.

## Using it

- Interpret requests, code, and docs with these meanings.
- When code or docs use a term differently from its definition, report the mismatch with locations. It may be drift, a documentation error, or a definition that needs clarifying. Don't assume the code defines the intended meaning, and don't silently rename anything.

## File conventions

All entries live in `.coherence/domain.md`, one `##` heading each, so agents can read the whole domain at once. Don't add an index table, split terms into separate files, or repeat definitions in `index.md`; the site's "On this page" sidebar lists the headings. Link to a term with `[Observation](domain.md#observation)`. Renaming a heading changes its anchor, so update links in the same change.
