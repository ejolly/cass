# Agent skill

cass ships a Claude Code skill. It tells an agent which cass command fits a Canvas task, how to preview writes safely, and which Canvas quirks to expect. The skill is bundled with cass, so it describes the commands of the version you have installed.

## Install

```bash
cass skill install                      # copies the skill to ~/.claude/skills/cass
cass skill install --dir .claude/skills # project-level instead
cass skill install --yes                # replace an existing copy without asking
```

Rerun it after upgrading cass to get the new skill.

## Contents

The skill is `SKILL.md`, reproduced below, plus reference files the agent reads on demand:

| File | Covers |
| --- | --- |
| `references/quirks.md` | Canvas behaviors cass has verified, and what cass does about each one |
| `references/files-and-modules.md` | Uploads, folders, duplicate handling, module items, `sync` and `--prune` |
| `references/quizzes.md` | Quiz file format, question editing, previews, responses |
| `references/late-enrollments.md` | Finding late-enrolled students, `excuse` and `clear-late` |

The sources are in `cass/skill/` in the repository. A test checks that every `cass …` command they mention exists and accepts the options shown.

## The skill

--8<-- "cass/skill/SKILL.md:body"
