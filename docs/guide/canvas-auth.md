# Canvas authentication

cass talks to Canvas either with an API token or with your browser's logged-in session.

## API token

Generate a token under **Account > Settings > Approved Integrations** in Canvas and paste it into `cass init`, which stores it in `.canvastoken`. This is the most reliable option when your institution allows it.

## Browser session

If tokens are disabled for you, reuse the session from a browser where you are logged in to Canvas. On macOS, with Brave or Google Chrome:

```bash
cass canvas login --from-brave
cass canvas login --from-chrome
```

Allow access to **Brave Safe Storage** or **Chrome Safe Storage** when macOS asks. cass copies the Canvas cookies, verifies the session, and writes `.canvascreds` with owner-only permissions.

For a non-default browser profile, pass the directory name shown under **Profile Path** at `brave://version` or `chrome://version`:

```bash
cass canvas login --from-chrome --profile "Profile 1"
```

### Refresh behavior

If Canvas rejects a request, cass re-reads the cookies from that browser profile and retries once. If the browser session itself has expired, log in to Canvas in the browser again and rerun the login command. CSRF errors point you to the same command but do not retry automatically.

### Other browsers

Copy `canvas_session` and `_csrf_token` from your browser's devtools (Application or Storage > Cookies) into `.canvascreds` in the course directory:

```
canvas_session=<value>
_csrf_token=<value>
```

Quotes around values are fine. Manually copied cookies do not refresh automatically.

## Switching back

`.canvascreds` takes priority over `.canvastoken`. Delete `.canvascreds` to return to token authentication.
