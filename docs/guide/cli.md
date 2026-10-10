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
cass canvas quizzes responses "Survey 1" --csv out.csv   # every student's answers
cass canvas calendar             # list / create / update / delete events
cass canvas upload file.pdf      # upload a file (delete-file removes one)
cass canvas announce "Title" "Body"   # update-announcement / delete-announcement
cass canvas sync [--apply]       # reconcile [[canvas.*]] declarations in cass.toml
cass canvas login --from-chrome  # browser-session auth, see Canvas authentication
cass canvas api GET /courses/{course}/modules --all     # raw API request
cass canvas api PUT /courses/{course}/modules/5 --data 'module[name]=Week1'
```

`cass canvas api` prints the response body as JSON. `{course}` expands to the configured course ID; `--param KEY=VALUE` adds query parameters and `--json-body` sends a JSON body. To call the API from Python, see the [Python API guide](python-api.md).

## Previewing changes

Every command that writes to Canvas takes `--dry-run`. It prints the requests the command would send and sends none; GETs still run.

```bash
cass canvas modules create "Week 9" --dry-run
cass push --dry-run                 # preview pending local changes
cass canvas sync                    # dry run by default
cass canvas sync --apply            # make the changes
```

Reconcile commands such as `sync` preview by default and change Canvas only with `--apply`. Commands that ask for confirmation take `--yes`; without a terminal they exit with code 1 rather than wait for input.

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
