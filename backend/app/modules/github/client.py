from datetime import datetime
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx
from fastapi import status

from app.core.config import settings


class GithubAPIError(Exception):
    """GitHub API rejected a request or returned invalid data."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class GithubClient:
    """Read-only GitHub REST API client for account, repository, and commit data."""

    def __init__(self, token: str, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = http_client is None
        self._api_base_url = settings.GITHUB_API_BASE_URL.rstrip("/") + "/"
        self._client = http_client or httpx.AsyncClient(
            base_url=self._api_base_url,
            timeout=httpx.Timeout(20.0, connect=5.0),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def __aenter__(self) -> "GithubClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    async def exchange_code(code: str) -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            try:
                response = await client.post(
                    "https://github.com/login/oauth/access_token",
                    json={
                        "client_id": settings.GITHUB_CLIENT_ID,
                        "client_secret": settings.GITHUB_CLIENT_SECRET,
                        "code": code,
                        "redirect_uri": settings.GITHUB_CALLBACK_URL,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.RequestError as exc:
                raise GithubAPIError("Could not reach GitHub OAuth.", 502) from exc
        if response.is_error:
            raise GithubAPIError("GitHub authorization could not be completed.", 502)
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise GithubAPIError("GitHub returned an invalid authorization response.") from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise GithubAPIError("GitHub did not return an access token.", 400)
        if payload.get("error"):
            raise GithubAPIError("GitHub authorization was denied.", 400)
        return token

    async def get_user(self) -> dict[str, Any]:
        result = await self._get_json("user")
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            raise GithubAPIError("GitHub returned invalid user information.")
        return result

    async def list_repositories(self) -> list[dict[str, Any]]:
        next_url: str | None = (
            "user/repos?affiliation=owner,collaborator,organization_member&sort=updated&per_page=100"
        )
        repositories: list[dict[str, Any]] = []
        pages = 0
        while next_url and pages < 100:
            response = await self._get_response(next_url)
            try:
                page: Any = response.json()
            except ValueError as exc:
                raise GithubAPIError("GitHub returned invalid repository data.") from exc
            if not isinstance(page, list):
                raise GithubAPIError("GitHub returned invalid repository data.")
            if any(
                not isinstance(repository, dict)
                or not isinstance(repository.get("id"), int)
                or not isinstance(repository.get("full_name"), str)
                for repository in page
            ):
                raise GithubAPIError("GitHub returned invalid repository data.")
            repositories.extend(page)
            pages += 1
            next_url = _next_link(response.headers.get("Link"), self._api_base_url)
        if next_url:
            raise GithubAPIError(
                "GitHub account has too many repositories to load in one request; narrow repository access.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        return repositories

    async def list_commits(
        self,
        full_name: str,
        *,
        since: datetime | None,
        page_limit: int = 5,
    ) -> list[dict[str, Any]]:
        query = "per_page=100"
        if since is not None:
            query += f"&since={since.isoformat()}"
        next_url: str | None = f"repos/{quote(full_name, safe='/')}/commits?{query}"
        commits: list[dict[str, Any]] = []
        pages = 0
        while next_url and pages < page_limit:
            response = await self._get_response(next_url)
            try:
                page: Any = response.json()
            except ValueError as exc:
                raise GithubAPIError("GitHub returned invalid commit data.") from exc
            if not isinstance(page, list):
                raise GithubAPIError("GitHub returned invalid commit data.")
            if any(
                not isinstance(commit, dict) or not isinstance(commit.get("sha"), str)
                for commit in page
            ):
                raise GithubAPIError("GitHub returned invalid commit data.")
            commits.extend(page)
            pages += 1
            next_url = _next_link(response.headers.get("Link"), self._api_base_url)
        return commits

    async def get_commit_stats(self, full_name: str, sha: str) -> dict[str, int]:
        response = await self._get_json(f"repos/{full_name}/commits/{sha}")
        stats = response.get("stats", {}) if isinstance(response, dict) else {}
        files = response.get("files", []) if isinstance(response, dict) else []
        if not isinstance(stats, dict):
            stats = {}
        return {
            "additions": _nonnegative_int(stats.get("additions")),
            "deletions": _nonnegative_int(stats.get("deletions")),
            "changed_files": len(files) if isinstance(files, list) else 0,
        }

    async def _get_json(self, path: str) -> Any:
        response = await self._get_response(path)
        try:
            return response.json()
        except ValueError as exc:
            raise GithubAPIError("GitHub returned invalid data.") from exc

    async def _get_response(self, path: str) -> httpx.Response:
        if path.startswith(("http://", "https://")):
            requested_origin = urlsplit(path)
            api_origin = urlsplit(self._api_base_url)
            if (
                requested_origin.scheme != api_origin.scheme
                or requested_origin.netloc != api_origin.netloc
            ):
                raise GithubAPIError("GitHub returned a pagination link to an unexpected host.")
        try:
            response = await self._client.get(path)
        except httpx.RequestError as exc:
            raise GithubAPIError("Could not reach the GitHub API.") from exc
        if response.is_error:
            if response.status_code == 401:
                message = "GitHub authorization expired or was revoked. Reconnect the account."
            elif (
                response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0"
            ):
                message = "GitHub API rate limit reached. Retry after the reset time."
            elif response.status_code == 404:
                message = "GitHub repository or resource is unavailable to this account."
            else:
                message = f"GitHub API request failed with status {response.status_code}."
            raise GithubAPIError(
                message, response.status_code if response.status_code < 500 else 502
            )
        return response


def _next_link(link_header: str | None, api_base_url: str) -> str | None:
    if not link_header:
        return None
    for entry in link_header.split(","):
        url, *attributes = entry.strip().split(";")
        if any(attribute.strip() == 'rel="next"' for attribute in attributes):
            next_url = urljoin(api_base_url, url.strip("<>"))
            next_origin = urlsplit(next_url)
            api_origin = urlsplit(api_base_url)
            if next_origin.scheme != api_origin.scheme or next_origin.netloc != api_origin.netloc:
                raise GithubAPIError("GitHub returned a pagination link to an unexpected host.")
            return next_url
    return None


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
