"""GitHub Issues sink: one upserted issue per episode key, located via an embedded marker."""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Any

import httpx

API_ROOT = "https://api.github.com"
BASE_LABEL = "space-weather"

# Same retry philosophy as sources/http.py (spec 8.1): GitHub has bad minutes too, and a
# single 503 on the marker search must not cost an alert its whole hour. 5xx and 429 are
# transient and retried over a widening window; every other 4xx fails immediately.
_RETRIES = 5
_BACKOFF_CAP_S = 10.0


def _backoff_s(attempt: int) -> float:
    ceiling = min(_BACKOFF_CAP_S, 2.0**attempt)
    return ceiling / 2 + random.uniform(0, ceiling / 2)


def key_marker(key: str) -> str:
    """An HTML comment: invisible in the rendered Issue, but findable by string match.
    This marker IS the idempotency mechanism — one key means one evolving Issue."""
    return f"<!-- nasa-space-weather-key: {key} -->"


class GitHubIssues:
    """GitHub issue sink for episode notifications."""

    def __init__(self, token: str, repo: str, client: httpx.Client | None = None):
        self.repo = repo
        self.client = client or httpx.Client(base_url=API_ROOT, timeout=30.0)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @classmethod
    def from_env(cls) -> "GitHubIssues":
        """Build a sink from the GITHUB_TOKEN and GITHUB_REPOSITORY variables Actions provides."""
        token = os.environ["GITHUB_TOKEN"]
        repo = os.environ["GITHUB_REPOSITORY"]
        return cls(token=token, repo=repo)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send one GitHub API request, retrying 5xx/429 with equal-jitter backoff and a
        numeric Retry-After when offered — so one bad GitHub minute does not eat an alert."""
        last: httpx.Response | None = None
        for attempt in range(_RETRIES):
            resp = self.client.request(method, url, headers=self._headers, **kwargs)
            if resp.status_code < 500 and resp.status_code != 429:
                resp.raise_for_status()  # 4xx is our mistake — repeating it would not help
                return resp
            last = resp
            if attempt == _RETRIES - 1:
                break
            retry_after = resp.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after is not None else _backoff_s(attempt)
            except ValueError:
                delay = _backoff_s(attempt)
            print(
                f"github {method} {url}: {resp.status_code}; "
                f"retry {attempt + 2}/{_RETRIES} in {delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
        assert last is not None
        last.raise_for_status()
        return last

    def _find_by_key(self, key: str) -> dict[str, Any] | None:
        marker = key_marker(key)
        page = 1
        while True:
            resp = self._request(
                "GET",
                f"/repos/{self.repo}/issues",
                params={"labels": BASE_LABEL, "state": "all", "per_page": 100, "page": page},
            )
            batch = resp.json()
            if not batch:
                return None
            for issue in batch:
                if marker in (issue.get("body") or ""):
                    return issue
            if len(batch) < 100:
                return None
            page += 1

    def upsert(self, key: str, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        """Create the issue for `key`, or update and reopen the existing one.

        Returns:
            A dict carrying the action taken ("created" or "updated") and the issue number.
        """
        existing = self._find_by_key(key)
        if existing is None:
            resp = self._request(
                "POST",
                f"/repos/{self.repo}/issues",
                json={"title": title, "body": body, "labels": labels},
            )
            return {"action": "created", "number": resp.json()["number"]}

        number = existing["number"]
        patch: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if existing.get("state") == "closed":
            patch["state"] = "open"
        self._request("PATCH", f"/repos/{self.repo}/issues/{number}", json=patch)
        if (existing.get("body") or "") != body:
            # Only announce an update when something actually changed — a retried upsert
            # with an identical body must not spam subscribers with "evolved" comments.
            self._request(
                "POST",
                f"/repos/{self.repo}/issues/{number}/comments",
                json={"body": "Updated: this episode has evolved (see body)."},
            )
        return {"action": "updated", "number": number}
