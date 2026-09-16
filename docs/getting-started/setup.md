# Setup

Run setup once per course, inside the directory where you want `cass.db` and `cass.toml` to live.

```bash
mkdir psyc-201 && cd psyc-201
cass init
```

`cass init` asks for:

1. **Canvas base URL**, for example `https://canvas.ucsd.edu`.
2. **Course ID**, the number in the course URL.
3. **Credentials.** Paste a Canvas API token to save it in `.canvastoken`, or skip and use your browser session instead (see [Canvas authentication](../guide/canvas-auth.md)).

It writes `cass.toml`, including the course time zone that all typed times are read in:

```toml
[canvas]
base_url = "https://canvas.ucsd.edu"
course_id = 72335
time_zone = "America/Los_Angeles"
```

Commit `cass.toml` if you like. Never commit `.canvastoken`, `.canvascreds`, or `cass.db`; `cass init` adds them to `.gitignore` for you if the directory is a git repo.

Then pull your course data:

```bash
cass pull
```
