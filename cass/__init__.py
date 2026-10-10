"""cass — Canvas grading CLI.

A workflow-oriented CLI for synchronizing local grading state with
Canvas LMS. Local data lives in a per-project SQLite database
(`cass.db`).

Install: `uv tool install cass` or `uvx cass`.

---

## Top-level Commands

| Command | Description |
|---------|-------------|
| `cass status` | Show local data and Canvas sync status |
| `cass init` | Initialize a new project or check setup |
| `cass pull` | Fetch from Canvas and update the local database |
| `cass push` | Preview and push pending local changes to Canvas |
| `cass revert` | Revert local changes since the last Canvas sync |
| `cass query` | Query curated datasets, with raw SQL as an escape hatch |
| `cass delete` | Delete the local database |
| `cass backup` | Save a timestamped copy of the database |
| `cass restore` | Replace the current database with a backup |
| `cass view` | Open the database in a browser-based viewer |

## Canvas Commands (`cass canvas`)

Every resource group has `list` (the bare group runs it). Commands acting on
one resource take an ID or a name. `list` accepts `--json`, as does `show` on
quizzes, modules and assignments (it displays one item). `tabs show` instead
makes a tab visible: a write that accepts `--dry-run`.

| Command | Description |
|---------|-------------|
| `cass canvas` | Course overview with resource counts |
| `cass canvas people list` | Show course roster with roles, emails and enrollment dates |
| `cass canvas sync` | Sync `cass.toml` declarations to Canvas |
| `cass canvas login` | Save a browser session for Canvas authentication |
| `cass canvas api` | Send a raw Canvas API request |

### Modules (`cass canvas modules`)

| Command | Description |
|---------|-------------|
| `cass canvas modules list` | List modules |
| `cass canvas modules show` | Show a module with its items |
| `cass canvas modules create` | Create a new module |
| `cass canvas modules publish` | Publish a module |
| `cass canvas modules unpublish` | Unpublish a module |
| `cass canvas modules delete` | Delete a module |
| `cass canvas modules items add` | Add an item to a module |
| `cass canvas modules items update` | Change an item's title, indent or visibility |
| `cass canvas modules items move` | Move an item within its module |
| `cass canvas modules items remove` | Remove an item from a module |

### Assignments (`cass canvas assignments`)

| Command | Description |
|---------|-------------|
| `cass canvas assignments list` | List assignments |
| `cass canvas assignments show` | Show one assignment |
| `cass canvas assignments groups list` | Show assignment groups with weights |
| `cass canvas assignments create` | Create a new assignment |
| `cass canvas assignments publish` | Publish an assignment |
| `cass canvas assignments unpublish` | Unpublish an assignment |
| `cass canvas assignments delete` | Delete an assignment |

### Quizzes (`cass canvas quizzes`)

| Command | Description |
|---------|-------------|
| `cass canvas quizzes list` | List quizzes |
| `cass canvas quizzes show` | Show a quiz's settings and questions |
| `cass canvas quizzes export` | Write a quiz as a TOML file |
| `cass canvas quizzes create` | Create a new quiz |
| `cass canvas quizzes update` | Update a quiz's settings |
| `cass canvas quizzes publish` | Publish a quiz |
| `cass canvas quizzes unpublish` | Unpublish a quiz |
| `cass canvas quizzes delete` | Delete a quiz |
| `cass canvas quizzes responses` | Download every student's answers |

### Submissions (`cass canvas submissions`)

| Command | Description |
|---------|-------------|
| `cass canvas submissions list` | Show each student's submission state, lateness and score |
| `cass canvas submissions excuse` | Excuse submissions (dry run unless --apply) |
| `cass canvas submissions clear-late` | Clear late flags (dry run unless --apply) |

### Files

| Command | Description |
|---------|-------------|
| `cass canvas files list` | Show course files as a tree |
| `cass canvas files upload` | Upload a file to the course |
| `cass canvas files delete` | Delete a file from the course |

### Announcements

| Command | Description |
|---------|-------------|
| `cass canvas announcements list` | List course announcements |
| `cass canvas announcements create` | Create an announcement |
| `cass canvas announcements update` | Update an announcement |
| `cass canvas announcements delete` | Delete an announcement |

### Tabs

| Command | Description |
|---------|-------------|
| `cass canvas tabs list` | List course navigation tabs |
| `cass canvas tabs show` | Make a navigation tab visible |
| `cass canvas tabs hide` | Hide a navigation tab |

### Calendar (`cass canvas calendar`)

| Command | Description |
|---------|-------------|
| `cass canvas calendar list` | List course calendar events |
| `cass canvas calendar create` | Create a calendar event |
| `cass canvas calendar update` | Update a calendar event |
| `cass canvas calendar delete` | Delete a calendar event |

## Output

`--json` prints JSON Lines (one object per line, Canvas field names) on list
commands and one object on `show` commands that display an item, and on
`cass status`. stdout carries only data; hints, progress, prompts and errors
go to stderr. Errors exit 1, usage errors exit 2. `--debug` is a global option
placed before the subcommand (`cass --debug canvas quizzes list`); or set
`CASS_DEBUG=1`. Either shows the full traceback.
"""  # noqa: E501

import importlib.metadata

__version__ = importlib.metadata.version("cassroom")
