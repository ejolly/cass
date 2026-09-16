# cass

Grading toolkit for [Canvas LMS](https://www.instructure.com/canvas) and [GitHub Classroom](https://classroom.github.com/) — pull rosters, track submissions, edit grades, and push them back to Canvas.

All data lives in a local SQLite database (`cass.db`) alongside a version-trackable `cass.toml` config.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [GitHub CLI](https://cli.github.com/) (`gh`) — required for install and for GitHub Classroom features

## Install

```bash
# Check authentication with GitHub (one-time)
gh auth status

# Login if needed
gh auth login
```

### Stable release (recommended)

```bash
uv tool install cassroom
```

To update:

```bash
uv tool install cassroom --upgrade
```

### From GitHub (latest)

```bash
uv tool install git+https://github.com/ejolly/cass.git
```

To update:

```bash
uv tool install git+https://github.com/ejolly/cass.git --reinstall
```

After install, `cass` is available globally.

## Get started

### Setup (one-time)

```bash
# Will ask you for canvas token and save to .canvastoken
cass init
```

#### No API token? Use your browser session instead

On macOS, log in to Canvas in Brave or Google Chrome, then run the matching command:

```bash
cass canvas login --from-brave
cass canvas login --from-chrome
```

Allow access to **Brave Safe Storage** or **Chrome Safe Storage** if macOS asks.
cass imports your Canvas cookies, checks the session, and saves `.canvascreds`
with owner-only permissions.
For another browser profile, add `--profile "Profile 1"`, using the directory name
shown in `brave://version` or `chrome://version` under **Profile Path**.

If Canvas rejects authentication, cass refreshes the cookies from that profile
and retries the request once. If the browser session has also expired, log in to
Canvas in that browser and rerun the login command. CSRF errors also point to this
command, but do not trigger an automatic retry.

For other browsers, copy `canvas_session` and `_csrf_token` from devtools
(Application/Storage > Cookies) into `.canvascreds` in the project root:

```
canvas_session=<value>
_csrf_token=<value>
```

Quotes around the values are fine. Manually copied cookies do not refresh
automatically. `.canvascreds` takes priority over `.canvastoken`; delete it to
return to API-token authentication.

### Pull latest data

```bash
cass pull
```

### Open Viewer

```bash
cass view
```

- The only tables/spreadsheets you can edit in the viewer are Canvas Gradebook & Assignments
- Just double-click a cell to edit the value like in google-sheets. Changed cells will appear in orange. 
- When you're done editing press (e.g. multiple cells) press **push** button in the top left to send updates to Canvas

### CLI

Everything you can do from the viewer you (or Claude) can do from the CLI:

```bash
cass init         # interactive config setup
cass pull         # fetch students, assignments, submissions
cass status       # overview of local state and sync status
cass revert       # discard pending local changes
cass push         # preview + confirm pending Canvas changes
cass push --yes   # skip confirmation

# Canvas management
cass canvas                # course overview
cass canvas people         # enrolled students
cass canvas modules        # list / create / publish modules
cass canvas assignments    # list / create assignments (and groups)
cass canvas calendar       # list / create / update / delete events
cass canvas upload file.pdf
cass canvas announce "Title" "Body"

# Data management
# query also accepts --where, --order, and --limit
cass query students        # roster
cass query assignments     # assignment metadata
cass query submissions     # submissions dataset
cass query gradebook       # student x assignment matrix
cass query --sql "select count(*) from students"
cass backup                # timestamped snapshot → backups/
cass backup --tag "pre-regrade"
cass restore backups/cass_2026-03-05.db
```

Running `cass` with no arguments shows help.

## Configuration

`cass.toml` lives in your project root. Canvas is required; GitHub Classroom is optional.

```toml
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335

# Optional — enables submission tracking and roster matching
[classroom]
id = 299058
org = "psyc-201"
```

## Development

```bash
uv sync                    # install deps
uv run poe lint            # ruff format + check, ty
uv run poe test            # pytest
uv run poe install         # install as global CLI tool
```
