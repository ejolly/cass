"""cass — Classroom Assignment Grading CLI.

A CLI toolkit for grading assignments with **GitHub Classroom**,
**Canvas LMS**, or both.  Data is stored in a per-project DuckDB
database (`cass.duckdb`).

Install: `uv tool install cass` or `uvx cass`.

---

## Commands

| Command | Description |
|---------|-------------|
| `cass` | Project status dashboard (default) |
| `cass init` | Initialize a new project or check setup |
| `cass pull` | Fetch from APIs and update the local database |
| `cass students` | Show the student roster |
| `cass assignments` | Show assignment metadata |
| `cass submissions` | View submission status |
| `cass fetch` | Download student submission files |
| `cass drop` | Delete the local database |
| `cass backup` | Save a timestamped copy of the database |
| `cass restore` | Replace the current database with a backup |
| `cass query` | Run a DuckDB SQL query (or interactive REPL) |
| `cass export` | Export a database table to CSV or markdown |
| `cass import` | Import a CSV file into the database |
| `cass view` | Open the database in a browser-based viewer |

## Gradebook Commands (`cass gradebook`)

| Command | Description |
|---------|-------------|
| `cass gradebook` | Show the gradebook as a student x assignment matrix |
| `cass gradebook push` | Sync grades to Canvas LMS (dry-run by default) |

## Database Commands (`cass db`)

| Command | Description |
|---------|-------------|
| `cass db` | Interactive DuckDB REPL |
| `cass db clean` | Clear API cache for lean git commits |

## Canvas Commands (`cass canvas`)

| Command | Description |
|---------|-------------|
| `cass canvas` | Course overview with resource counts |
| `cass canvas people` | Show course roster with roles and emails |
| `cass canvas sync` | Sync cass.toml declarations to Canvas |

### Modules (`cass canvas modules`)

| Command | Description |
|---------|-------------|
| `cass canvas modules` | List modules (with items) |
| `cass canvas modules create` | Create a new module |
| `cass canvas modules publish` | Publish a module |
| `cass canvas modules unpublish` | Unpublish a module |
| `cass canvas modules delete` | Delete a module |
| `cass canvas modules add-item` | Add an item to a module |

### Assignments (`cass canvas assignments`)

| Command | Description |
|---------|-------------|
| `cass canvas assignments` | List assignments |
| `cass canvas assignments groups` | Show assignment groups with weights |
| `cass canvas assignments create` | Create a new assignment |
| `cass canvas assignments publish` | Publish an assignment |
| `cass canvas assignments unpublish` | Unpublish an assignment |
| `cass canvas assignments delete` | Delete an assignment |

### Quizzes (`cass canvas quizzes`)

| Command | Description |
|---------|-------------|
| `cass canvas quizzes` | List quizzes |
| `cass canvas quizzes create` | Create a new quiz |
| `cass canvas quizzes publish` | Publish a quiz |
| `cass canvas quizzes unpublish` | Unpublish a quiz |
| `cass canvas quizzes delete` | Delete a quiz |

### Files

| Command | Description |
|---------|-------------|
| `cass canvas files` | Show course files as a tree |
| `cass canvas upload` | Upload a file to the course |
| `cass canvas delete-file` | Delete a file from the course |

### Announcements

| Command | Description |
|---------|-------------|
| `cass canvas announcements` | List course announcements |
| `cass canvas announce` | Create an announcement |
| `cass canvas update-announcement` | Update an announcement |
| `cass canvas delete-announcement` | Delete an announcement |

### Tabs

| Command | Description |
|---------|-------------|
| `cass canvas tabs` | List course navigation tabs |
| `cass canvas show-tab` | Make a navigation tab visible |
| `cass canvas hide-tab` | Hide a navigation tab |
"""

__version__ = "0.2.0"
