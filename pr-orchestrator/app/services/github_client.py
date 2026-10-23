import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings


class GitHubClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        token = self.settings.github_token.get_secret_value()
        if not token:
            raise RuntimeError("GITHUB_TOKEN is required to process pull requests")
        self.client = httpx.AsyncClient(
            base_url=self.settings.github_api_url.rstrip("/"),
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": self.settings.github_api_version,
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _repo_path(self, repository: str) -> str:
        return f"/repos/{repository}"

    async def get_pull_diff(self, repository: str, number: int) -> str:
        response = await self.client.get(
            f"{self._repo_path(repository)}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        response.raise_for_status()
        return response.text

    async def get_pull_files(self, repository: str, number: int) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"{self._repo_path(repository)}/pulls/{number}/files",
            params={"per_page": 100},
        )
        response.raise_for_status()
        return response.json()

    async def _get_codeowners_text(self, repository: str, ref: str) -> str:
        for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            response = await self.client.get(
                f"{self._repo_path(repository)}/contents/{quote(path, safe='/')}",
                params={"ref": ref},
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            body = response.json()
            if body.get("encoding") == "base64":
                return base64.b64decode(body["content"]).decode("utf-8")
        return ""

    async def get_codeowners(self, repository: str, ref: str) -> str:
        return await self._get_codeowners_text(repository, ref)

    async def get_recent_file_authors(
        self, repository: str, paths: list[str], base: str, limit: int = 10
    ) -> list[str]:
        authors: dict[str, int] = {}
        for path in paths[:limit]:
            response = await self.client.get(
                f"{self._repo_path(repository)}/commits",
                params={"path": path, "per_page": 5, "sha": base},
            )
            response.raise_for_status()
            for commit in response.json():
                author = commit.get("author") or {}
                login = author.get("login")
                if login:
                    authors[login] = authors.get(login, 0) + 1
        return sorted(authors, key=authors.get, reverse=True)

    async def post_pr_comment(self, repository: str, number: int, body: str) -> None:
        response = await self.client.post(
            f"{self._repo_path(repository)}/issues/{number}/comments",
            json={"body": body},
        )
        response.raise_for_status()

    async def request_reviewers(
        self, repository: str, number: int, reviewers: list[str]
    ) -> None:
        if not reviewers:
            return
        users = [reviewer for reviewer in reviewers if "/" not in reviewer]
        teams = [reviewer for reviewer in reviewers if "/" in reviewer]
        response = await self.client.post(
            f"{self._repo_path(repository)}/pulls/{number}/requested_reviewers",
            json={"reviewers": users, "team_reviewers": teams},
        )
        response.raise_for_status()
