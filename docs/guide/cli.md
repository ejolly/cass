# CLI

Everything the viewer does also works from the terminal, which makes cass scriptable and usable from coding agents. Every command accepts `--help`. The full generated reference is on the [CLI reference](../reference/cli.md) page.

## Core

```bash
cass init         # interactive setup
cass pull         # fetch students, assignments, submissions
cass status       # local state and sync status
cass view         # open the browser viewer
cass push         # preview and confirm pending Canvas changes
cass push --yes   # skip confirmation
cass revert       # discard pending local changes
```

## Canvas management

```bash
cass canvas                      # course overview
cass canvas people               # roster with roles and emails
cass canvas files                # course files as a tree
cass canvas announcements        # list announcements
cass canvas tabs                 # navigation tabs; show-tab / hide-tab change visibility
cass canvas modules              # list / create / publish / delete modules
cass canvas assignments          # list / create / publish / delete assignments and groups
cass canvas quizzes              # list quizzes; see the Quizzes guide for authoring
cass canvas calendar             # list / create / update / delete events
cass canvas upload file.pdf      # upload a file (delete-file removes one)
cass canvas announce "Title" "Body"   # update-announcement / delete-announcement
cass canvas sync [--apply]       # reconcile [[canvas.*]] declarations in cass.toml
cass canvas login --from-chrome  # browser-session auth, see Canvas authentication
```

## Data

```bash
cass query students                     # roster
cass query assignments                  # assignment metadata
cass query submissions                  # submissions joined with names
cass query gradebook                    # student x assignment matrix
cass query gradebook --where "score < 50" --order name --limit 20
cass query --sql "select count(*) from canvas_students"
cass backup [--tag NAME]
cass restore PATH
cass delete                             # remove local database
```

## Another course

Every command accepts `--config PATH` (or the `CASS_CONFIG` environment variable) to run against a different `cass.toml`. Credentials and `cass.db` resolve beside that file.

```bash
cass --config ../f25/cass.toml canvas quizzes
```
