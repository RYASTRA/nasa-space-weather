from __future__ import annotations

import os
from typing import Any

import httpx

API_ROOT = "https://api.github.com"
BASE_LABEL = "space-weather"


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
        token = os.environ["GITHUB_TOKEN"]
        repo = os.environ["GITHUB_REPOSITORY"]
        return cls(token=token, repo=repo)

    def _find_by_key(self, key: str) -> dict[str, Any] | None:
        marker = key_marker(key)
        page = 1
        while True:
            resp = self.client.get(
                f"/repos/{self.repo}/issues",
                headers=self._headers,
                params={"labels": BASE_LABEL, "state": "all", "per_page": 100, "page": page},
            )
            resp.raise_for_status()
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
        existing = self._find_by_key(key)
        if existing is None:
            resp = self.client.post(
                f"/repos/{self.repo}/issues",
                headers=self._headers,
                json={"title": title, "body": body, "labels": labels},
            )
            resp.raise_for_status()
            return {"action": "created", "number": resp.json()["number"]}

        number = existing["number"]
        patch: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if existing.get("state") == "closed":
            patch["state"] = "open"
        resp = self.client.patch(
            f"/repos/{self.repo}/issues/{number}", headers=self._headers, json=patch
        )
        resp.raise_for_status()
        comment = self.client.post(
            f"/repos/{self.repo}/issues/{number}/comments",
            headers=self._headers,
            json={"body": "Updated: this episode has evolved (see body)."},
        )
        comment.raise_for_status()
        return {"action": "updated", "number": number}
