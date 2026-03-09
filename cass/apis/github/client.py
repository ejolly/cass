"""Async GitHub API client using httpx — replaces gh subprocess calls for pull."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
import json
import re
import shutil
import subprocess

import httpx

from ...db import cache

_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
MAX_CONCURRENCY = 10


class GitHubClientError(RuntimeError):
    """Structured GitHub integration error with an actionable code."""

    def __init__(self, code: str, detail: str, hint: str = "") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.hint = hint

    @property
    def display_message(self) -> str:
        if self.hint:
            return f"{self.detail} {self.hint}"
        return self.detail


def check_available() -> bool:
    """Return True if ``gh`` is on PATH."""
    return shutil.which("gh") is not None


def check_auth() -> tuple[bool, str]:
    """Check ``gh auth status``. Returns (is_authed, username_or_error)."""
    if not check_available():
        return False, "Install GitHub CLI: https://cli.github.com/"
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        if "token in default is invalid" in detail:
            return False, "Run `gh auth login -h github.com`."
        if "not logged in" in detail.lower():
            return False, "Run `gh auth login -h github.com`."
        return False, detail or "Run `gh auth login -h github.com`."
    for line in result.stderr.splitlines():
        if "Logged in to" in line and "account" in line:
            parts = line.split("account")
            if len(parts) > 1:
                return True, parts[1].strip().split()[0]
    return True, "(authenticated)"


def get_token() -> str:
    """Get GitHub token from the gh CLI (one subprocess call)."""
    if not shutil.which("gh"):
        raise GitHubClientError(
            "gh_missing",
            "GitHub CLI is not installed.",
            "Install GitHub CLI: https://cli.github.com/",
        )
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip()
        if "token in default is invalid" in detail:
            raise GitHubClientError(
                "gh_auth_invalid",
                "GitHub authentication is invalid.",
                "Run `gh auth login -h github.com`.",
            )
        raise GitHubClientError(
            "gh_auth_missing",
            "GitHub authentication is missing.",
            "Run `gh auth login -h github.com`.",
        )
    token = result.stdout.strip()
    if not token:
        raise GitHubClientError(
            "gh_auth_missing",
            "GitHub authentication is missing.",
            "Run `gh auth login -h github.com`.",
        )
    return token


class GitHubClient:
    """Async GitHub API client with caching and concurrency control."""

    def __init__(self) -> None:
        token = get_token()
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _fetch(self, endpoint: str, paginate: bool = False) -> object:
        """HTTP GET with concurrency control and optional pagination."""
        async with self._sem:
            if not paginate:
                resp = await self._client.get(endpoint)
                resp.raise_for_status()
                return resp.json()

            results: list[object] = []
            sep = "&" if "?" in endpoint else "?"
            url: str | None = f"{endpoint}{sep}per_page=100"
            while url:
                resp = await self._client.get(url)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    results.extend(data)  # pyright: ignore[reportUnknownArgumentType]
                else:
                    return data
                url = None
                link = resp.headers.get("link", "")
                if m := _LINK_NEXT_RE.search(link):
                    next_url = m.group(1)
                    base = str(self._client.base_url)
                    url = next_url.removeprefix(base)
            return results

    async def get_cached(
        self,
        endpoint: str,
        ttl_hours: float = 6,
        force_refresh: bool = False,
        paginate: bool = False,
    ) -> object:
        """Cache-through fetch — checks SQLite cache first."""
        if not force_refresh:
            raw = cache.cache_load(endpoint, ttl_hours)
            if raw is not None:
                return json.loads(raw)
        data = await self._fetch(endpoint, paginate)
        cache.cache_save(endpoint, json.dumps(data))
        return data

    async def exists_cached(
        self,
        endpoint: str,
        ttl_hours: float = 6,
        force_refresh: bool = False,
    ) -> bool:
        """Check if a resource exists (200 -> True, 404 -> False). Cached."""
        if not force_refresh:
            raw = cache.cache_load(endpoint, ttl_hours)
            if raw is not None:
                return json.loads(raw) is True
        try:
            async with self._sem:
                resp = await self._client.get(endpoint)
                exists = resp.status_code == 200
        except httpx.HTTPError:
            exists = False
        cache.cache_save(endpoint, json.dumps(exists))
        return exists
