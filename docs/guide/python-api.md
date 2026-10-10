# Python API

`CanvasClient` is the same client the CLI uses. Use it to script Canvas from Python, including endpoints cass has no command for.

## Open a client

```python
from cass.apis.canvas.client import CanvasClient

with CanvasClient() as c:                       # the project's cass.toml
    print(c.list_modules())

with CanvasClient.from_config("../f25/cass.toml") as c:   # another course
    ...
```

`from_config` reads the base URL, course ID and time zone from the given file and the credentials from its directory.

## Raw API requests

`get_all` follows pagination and returns the items as a list. `request` sends any method and returns the `httpx.Response`. `course_path` prefixes a path with `/courses/{id}`.

```python
with CanvasClient() as c:
    quizzes = c.get_all(c.course_path("/quizzes"), params=[("include[]", "assignment")])

    c.request("PUT", c.course_path("/modules/5"), data=[("module[name]", "Week 1")])
```

Pass `params` and `data` as lists of pairs when a key repeats. Paths may be written `/api/v1/x`, `/x` or `x`.

The CLI equivalent is `cass canvas api`; see the [CLI guide](cli.md).

## Errors

Any 4xx/5xx response raises `CanvasAPIError`, a subclass of `httpx.HTTPStatusError`.

```python
from cass.apis.canvas.client import CanvasAPIError

try:
    c.request("DELETE", c.course_path("/modules/999"))
except CanvasAPIError as err:
    print(err.status_code, err.canvas_message)
```

## Dry run

A client built with `dry_run=True` sends GETs to Canvas but records every write instead of sending it. `planned_requests` holds the records and `format_plan` renders them.

```python
from cass.apis.canvas.dry_run import format_plan

with CanvasClient.from_config("cass.toml", dry_run=True) as c:
    c.create_module("Week 9")
    print("\n".join(format_plan(c.planned_requests)))
```

Each write gets a successful synthetic response, so later steps that depend on it still run. Created resources receive placeholder IDs, shown in the plan as `<new N>`.
