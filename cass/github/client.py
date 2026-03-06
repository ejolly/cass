"""Async GitHub API client using httpx — replaces gh subprocess calls for pull."""

from __future__ import annotations

__docformat__ = "google"

import asyncio
import json
import re
import shutil
import subprocess

import httpx

from .. import cache

_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')
MAX_CONCURRENCY = 10


def _get_token() -> str:
    """Get GitHub token from the gh CLI (one subprocess call)."""
    if not shutil.which("gh"):
        raise SystemExit(
            "Error: `gh` CLI not found. Install it: https://cli.github.com/"
        )
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("Not authenticated with GitHub. Run `gh auth login` first.")
    return result.stdout.strip()


class GitHubClient:
    """Async GitHub API client with caching and concurrency control."""

    def __init__(self) -> None:
        token = _get_token()
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

    async def _fetch(self, endpoint: str, paginate: bool = False) -> dict | list:
        """HTTP GET with concurrency control and optional pagination."""
        async with self._sem:
            if not paginate:
                resp = await self._client.get(endpoint)
                resp.raise_for_status()
                return resp.json()

            results: list = []
            sep = "&" if "?" in endpoint else "?"
            url: str | None = f"{endpoint}{sep}per_page=100"
            while url:
                resp = await self._client.get(url)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    results.extend(data)
                else:
                    return data
                url = None
                link = resp.headers.get("link", "")
                if m := _LINK_NEXT_RE.search(link):
                    next_url = m.group(1)
                    base = str(self._client.base_url)
                    url = (
                        next_url[len(base) :] if next_url.startswith(base) else next_url
                    )
            return results

    async def get_cached(
        self,
        endpoint: str,
        ttl_hours: float = 6,
        force_refresh: bool = False,
        paginate: bool = False,
    ) -> dict | list:
        """Cache-through fetch — checks DuckDB cache first."""
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
