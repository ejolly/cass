# DuckDB CLI Tutorial for cass

Your cass project stores everything in `cass.db` (DuckDB v1.4.4). When `cass` doesn't have the query you need, drop to the DuckDB CLI directly.

---

## Opening Your Database

```bash
# Interactive REPL on the cass database
duckdb cass.db

# Read-only (safe for poking around)
duckdb -readonly cass.db

# Run a one-liner without entering the REPL
duckdb cass.db "SELECT COUNT(*) FROM students"

# Multiple one-liners
duckdb cass.db -c "SELECT * FROM students LIMIT 5" -c "SELECT * FROM assignments LIMIT 5"
```

The `cass query` command also gives you a REPL, but the raw `duckdb` CLI has more features (output modes, `.import`, `.once`, UI, etc).

---

## Orientation: What's In the DB

```sql
-- List all tables
.tables

-- Show schema for a specific table
.schema students

-- Show all schemas
.schema

-- Row counts for everything
SELECT table_name, estimated_row_count
FROM duckdb_tables()
ORDER BY table_name;
```

### cass tables at a glance

| Table | Key columns |
|-------|-------------|
| `students` | identifier, github_username, name, canvas_id, excluded |
| `assignments` | id, source, title, slug, deadline, points_possible |
| `submissions` | student_id, assignment_id, source, submitted, late, score |
| `grades` | student_id, assignment_id, grade, numeric, source |
| `api_cache` | endpoint, data (JSON), fetched_at |
| `meta` | key, value (schema_version) |

---

## Output Modes

DuckDB defaults to `duckbox` (the fancy auto-sizing table). Switch modes for different workflows:

```sql
-- Pretty table (default) — great for eyeballing
.mode duckbox

-- Markdown — paste into docs/Slack/GitHub
.mode markdown
SELECT * FROM students LIMIT 5;

-- CSV — for export
.mode csv
SELECT * FROM students;

-- JSON — for piping into jaq/jq
.mode json
SELECT * FROM grades LIMIT 3;

-- Line — one column per line, useful for wide rows
.mode line
SELECT * FROM assignments WHERE slug = 'hw-01';

-- Reset back to default
.mode duckbox
```

You can also set the mode from the command line:

```bash
duckdb -markdown cass.db "SELECT * FROM students LIMIT 5"
duckdb -csv cass.db "SELECT * FROM assignments"
duckdb -json cass.db "SELECT * FROM grades LIMIT 3"
```

---

## Exporting Data

### Export to CSV

```sql
-- Method 1: COPY ... TO (best for full tables or complex queries)
COPY students TO 'students.csv' (HEADER, DELIMITER ',');
COPY (SELECT * FROM grades WHERE numeric > 0) TO 'passing.csv' (HEADER, DELIMITER ',');

-- Method 2: .once sends the next query's output to a file
.mode csv
.once students.csv
SELECT * FROM students;
```

Or from the command line (no REPL needed):

```bash
duckdb -csv -noheader cass.db "SELECT * FROM students" > students_noheader.csv
duckdb -csv cass.db "SELECT * FROM students" > students.csv
```

### Export to Markdown

```bash
# One-liner to markdown file
duckdb -markdown cass.db "SELECT identifier, name FROM students ORDER BY identifier" > roster.md
```

Or inside the REPL:

```sql
.mode markdown
.once roster.md
SELECT identifier, name FROM students ORDER BY identifier;
```

### Export to JSON

```sql
COPY students TO 'students.json' (FORMAT JSON);

-- Or from CLI:
-- duckdb -json cass.db "SELECT * FROM students" > students.json
```

### Export to Parquet (for sharing with Polars/Pandas later)

```sql
COPY students TO 'students.parquet' (FORMAT PARQUET);
```

---

## Importing Data

### Import CSV

```sql
-- Create a table directly from a CSV (auto-detects types)
CREATE TABLE new_roster AS SELECT * FROM read_csv('roster.csv');

-- Or read it as a query without creating a table
SELECT * FROM read_csv('extra_students.csv');

-- Import into an existing table (columns must match)
INSERT INTO students SELECT * FROM read_csv('more_students.csv');

-- With explicit options
SELECT * FROM read_csv('messy.csv',
    delim = ',',
    header = true,
    nullstr = 'NA',
    columns = {'name': 'VARCHAR', 'score': 'DOUBLE'}
);
```

### Import JSON

```sql
SELECT * FROM read_json('data.json');
CREATE TABLE imported AS SELECT * FROM read_json('api_response.json');
```

### Import Parquet

```sql
SELECT * FROM read_parquet('data.parquet');

-- Glob multiple files
SELECT * FROM read_parquet('exports/*.parquet');
```

### Import directly from a URL

```sql
SELECT * FROM read_csv('https://example.com/data.csv');
```

---

## Useful Queries for cass

```sql
-- Full gradebook: student × assignment matrix (pivot)
PIVOT grades ON assignment_id USING first(grade) GROUP BY student_id ORDER BY student_id;

-- Students missing submissions for a specific assignment
SELECT s.identifier, s.name
FROM students s
WHERE s.excluded = false
  AND s.identifier NOT IN (
    SELECT student_id FROM submissions WHERE assignment_id = 'hw-01'
  );

-- Late submission summary
SELECT assignment_id, COUNT(*) AS late_count
FROM submissions
WHERE late = true
GROUP BY assignment_id
ORDER BY late_count DESC;

-- Average score by assignment (Canvas submissions)
SELECT assignment_id, ROUND(AVG(score), 2) AS avg_score, COUNT(*) AS n
FROM submissions
WHERE source = 'canvas' AND score IS NOT NULL
GROUP BY assignment_id
ORDER BY assignment_id;

-- Cache age check (how stale is your data?)
SELECT endpoint,
       ROUND((epoch(now()) - fetched_at) / 3600, 1) AS hours_ago
FROM api_cache
ORDER BY fetched_at DESC;

-- Inspect cached API JSON (the data column stores raw JSON)
SELECT endpoint, json_extract(data, '$[0]') AS first_item
FROM api_cache
WHERE endpoint LIKE '%assignments%';

-- Summarize the entire database
SUMMARIZE students;
SUMMARIZE submissions;
```

---

## The Web UI (`-ui`)

DuckDB ships with a built-in web UI powered by the `ui` extension. It launches a local web app in your browser with a SQL editor, table browser, and result visualization.

```bash
# Launch the web UI on your cass database
duckdb -ui cass.db
```

This will:
1. Load the `ui` extension
2. Start a local web server
3. Open your browser to a MotherDuck-powered interface

From the UI you can:
- Browse tables and schemas visually
- Write and run SQL with autocomplete
- View results as tables or charts
- Export results from the browser

You can also start the UI from inside a REPL session:

```sql
-- Inside an existing duckdb session
.ui
```

Note: The UI extension phones home to MotherDuck's servers to serve the web app. If you're on an air-gapped network or want pure local, stick to the CLI.

### Where notebooks are stored

Notebooks are persisted globally (not per-database) at:

```
~/.duckdb/extension_data/ui/ui.db
```

This is a separate DuckDB database with tables `notebooks` and `notebook_versions`. You can inspect them:

```bash
duckdb -readonly ~/.duckdb/extension_data/ui/ui.db "SELECT id, name, created FROM notebooks"
```

---

## Handy Dot-Commands Reference

| Command | What it does |
|---------|-------------|
| `.tables` | List all tables |
| `.schema TABLE` | Show CREATE statement |
| `.mode MODE` | Set output: duckbox, csv, json, markdown, line, table |
| `.once FILE` | Send next query output to FILE |
| `.output FILE` | Send ALL subsequent output to FILE (`.output` to reset) |
| `.headers on/off` | Toggle column headers |
| `.timer on` | Show query execution time |
| `.maxrows N` | Limit displayed rows (duckbox mode) |
| `.excel` | Open next query result in your spreadsheet app |
| `.edit` | Open external editor to write a query |
| `.read FILE` | Execute SQL from a file |
| `.import FILE TABLE` | Import file into table |
| `.ui` | Launch web UI |
| `.quit` | Exit |

---

## Piping and Scripting

```bash
# Pipe a SQL file
duckdb cass.db < query.sql

# Use -f for the same thing
duckdb cass.db -f query.sql

# Chain with other CLI tools
duckdb -csv cass.db "SELECT identifier, name FROM students" | xan sort -s name

# Quick row count for all tables
duckdb cass.db "SELECT table_name, estimated_row_count FROM duckdb_tables()"
```

---

## Tips

- **SUMMARIZE**: `SUMMARIZE tablename` gives you column types, min/max/nulls/unique counts in one shot. Great for EDA.
- **DESCRIBE**: `DESCRIBE SELECT ...` shows the output schema of any query without running it.
- **Glob reads**: `SELECT * FROM read_csv('data/*.csv')` reads all matching files.
- **Attach multiple DBs**: `ATTACH 'other.db' AS other; SELECT * FROM other.students;`
- **Ephemeral DB**: `duckdb` with no filename creates an in-memory DB — useful for quick CSV wrangling without touching cass.db.
- **Safe exploration**: Use `-readonly` when you're just looking. Prevents accidental writes.
