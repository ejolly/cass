"""Subprocess wrapper for the GitHub CLI (`gh api`)."""

__docformat__ = "google"

import json
import shutil
import subprocess

from . import cache


def _require_gh() -> None:
    """Raise if ``gh`` is not on PATH."""
    if not shutil.which("gh"):
        raise SystemExit(
            "Error: `gh` CLI not found. Install it: https://cli.github.com/"
        )


def check_available() -> bool:
    """Return True if ``gh`` is on PATH."""
    return shutil.which("gh") is not None


def check_auth() -> tuple[bool, str]:
    """Check ``gh auth status``. Returns (is_authed, username_or_error)."""
    if not check_available():
        return False, "gh not installed"
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    # Parse username from stderr (gh auth status prints to stderr)
    for line in result.stderr.splitlines():
        if "Logged in to" in line and "account" in line:
            # "  Logged in to github.com account ejolly ..."
            parts = line.split("account")
            if len(parts) > 1:
                return True, parts[1].strip().split()[0]
    return True, "(authenticated)"


def api(endpoint: str, paginate: bool = False) -> dict | list:
    """Call `gh api` and return parsed JSON."""
    _require_gh()
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    # --paginate can return multiple JSON arrays concatenated; merge them
    text = result.stdout.strip()
    if paginate and text.startswith("["):
        merged = []
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(text):
            while pos < len(text) and text[pos] in " \t\n\r":
                pos += 1
            if pos >= len(text):
                break
            obj, end = decoder.raw_decode(text, pos)
            if isinstance(obj, list):
                merged.extend(obj)
            else:
                merged.append(obj)
            pos = end
        return merged
    return json.loads(text)


def api_cached(
    endpoint: str,
    ttl_hours: float = 6,
    force_refresh: bool = False,
    paginate: bool = False,
) -> dict | list:
    """Cache-through wrapper around api()."""
    if not force_refresh:
        raw = cache.cache_load(endpoint, ttl_hours)
        if raw is not None:
            cached = json.loads(raw)
            if isinstance(cached, (dict, list)):
                return cached
    data = api(endpoint, paginate=paginate)
    cache.cache_save(endpoint, json.dumps(data))
    return data
