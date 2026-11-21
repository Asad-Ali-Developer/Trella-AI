"""HTTP Client, API token Basic Auth, and OAuth handling for Jira Cloud."""

import asyncio
import base64
import ipaddress
import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.modules.jira.client")

_ATLASSIAN_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.atlassian\.net$")


class JiraAPIError(Exception):
    """Exception raised when Jira or Atlassian API requests fail."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class JiraRateLimitError(JiraAPIError):
    """Exception raised when Jira API rate limit (429) is exhausted after retries."""

    def __init__(self, message: str = "Jira API rate limit exceeded.") -> None:
        super().__init__(message, status_code=429)


def validate_jira_site_url(site_url: str) -> str:
    """Validate and normalize a Jira Cloud site URL to prevent SSRF.

    Rules:
    - Scheme must be https.
    - No userinfo (username/password) in URL.
    - Host must not be an IP literal.
    - Host must end with .atlassian.net (exact subdomain).
    - No non-443 port, query, or fragment.
    Returns normalized base URL without trailing slash: https://<tenant>.atlassian.net
    """
    raw = site_url.strip()
    if not raw:
        raise JiraAPIError("Jira site URL is required.", status_code=422)

    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https":
        raise JiraAPIError("Jira site URL must use HTTPS.", status_code=422)
    if parsed.username or parsed.password:
        raise JiraAPIError("Jira site URL must not include embedded credentials.", status_code=422)
    if parsed.query or parsed.fragment:
        raise JiraAPIError("Jira site URL must not contain query parameters or fragments.", status_code=422)
    if parsed.path not in ("", "/"):
        raise JiraAPIError("Jira site URL must not include a path.", status_code=422)

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise JiraAPIError("Jira site URL has an invalid host.", status_code=422)

    try:
        ipaddress.ip_address(hostname.strip("[]"))
        raise JiraAPIError("Jira site URL must not be an IP address.", status_code=422)
    except ValueError:
        pass

    try:
        port = parsed.port
    except ValueError as exc:
        raise JiraAPIError("Jira site URL has an invalid port.", status_code=422) from exc
    if port is not None and port != 443:
        raise JiraAPIError("Jira site URL must not specify a custom port.", status_code=422)

    if not hostname.endswith(".atlassian.net") or not _ATLASSIAN_SUBDOMAIN_RE.fullmatch(hostname):
        raise JiraAPIError(
            "Jira site URL host must be a valid *.atlassian.net domain.",
            status_code=422,
        )

    return f"https://{hostname}"


def validate_same_host_url(target_url: str, base_url: str) -> str:
    """Ensure a relative path or pagination URL resolves to the exact same HTTPS scheme and host."""
    resolved = urljoin(base_url.rstrip("/") + "/", target_url)
    target_parts = urlsplit(resolved)
    base_parts = urlsplit(base_url)

    if target_parts.scheme.lower() != "https" or base_parts.scheme.lower() != "https":
        raise JiraAPIError("Jira pagination link must use HTTPS.", status_code=502)
    if (
        target_parts.hostname != base_parts.hostname
        or target_parts.port != base_parts.port
        or target_parts.username
        or target_parts.password
    ):
        raise JiraAPIError("Jira returned a link to an unexpected host.", status_code=502)
    return resolved


class JiraOAuthTokens(BaseModel):
    """Atlassian OAuth 2.0 token response bundle."""

    access_token: str
    refresh_token: str
    expires_in: int = Field(default=3600)
    scope: str = Field(default="")
    token_type: str = Field(default="Bearer")


class JiraOAuthClient:
    """OAuth 2.0 client for Atlassian authorization and token management."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        auth_url: str | None = None,
    ) -> None:
        self.client_id = client_id or settings.JIRA_CLIENT_ID
        self.client_secret = client_secret or settings.JIRA_CLIENT_SECRET
        self.auth_url = (auth_url or settings.JIRA_AUTH_URL).rstrip("/")

    def authorization_url(
        self,
        *,
        state: str,
        redirect_uri: str,
        scopes: str | None = None,
    ) -> str:
        """Construct Atlassian 3LO authorization URL."""
        requested_scopes = scopes or settings.JIRA_SCOPES
        query_params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": requested_scopes,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        return f"{self.auth_url}/authorize?{urlencode(query_params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> JiraOAuthTokens:
        """Exchange authorization code for OAuth tokens."""
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            try:
                response = await client.post(
                    f"{self.auth_url}/oauth/token",
                    json=payload,
                )
                if response.status_code != 200:
                    logger.error(
                        "jira_token_exchange_failed",
                        status_code=response.status_code,
                    )
                    raise JiraAPIError(
                        f"Atlassian rejected authorization code (status {response.status_code}).",
                        status_code=response.status_code,
                    )
                return JiraOAuthTokens.model_validate(response.json())
            except httpx.RequestError as exc:
                logger.error("jira_token_exchange_request_error", error_type=type(exc).__name__)
                raise JiraAPIError("Network error contacting Atlassian OAuth.") from exc

    async def refresh_tokens(self, refresh_token: str) -> JiraOAuthTokens:
        """Refresh expired access token using the refresh token."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            try:
                response = await client.post(
                    f"{self.auth_url}/oauth/token",
                    json=payload,
                )
                if response.status_code != 200:
                    logger.error(
                        "jira_token_refresh_failed",
                        status_code=response.status_code,
                    )
                    raise JiraAPIError(
                        f"Failed to refresh Jira authorization (status {response.status_code}).",
                        status_code=response.status_code,
                    )
                return JiraOAuthTokens.model_validate(response.json())
            except httpx.RequestError as exc:
                logger.error("jira_token_refresh_request_error", error_type=type(exc).__name__)
                raise JiraAPIError("Network error refreshing Jira tokens.") from exc


class JiraClient:
    """Authenticated client for Jira Cloud REST API v3 (supports OAuth Bearer & API Token Basic Auth)."""

    def __init__(
        self,
        access_token: str = "",
        base_url: str | None = None,
        *,
        site_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self._owns_client = http_client is None
        self._client = http_client
        self.max_retries = max_retries
        self.site_url: str | None = None

        if site_url is not None or api_token is not None:
            if not site_url or not email or not api_token:
                raise JiraAPIError(
                    "Jira site URL, email, and API token are all required.",
                    status_code=422,
                )
            normalized_site = validate_jira_site_url(site_url)
            self.site_url = normalized_site
            self.base_url = normalized_site
            raw_creds = f"{email}:{api_token}".encode()
            b64_creds = base64.b64encode(raw_creds).decode("ascii")
            self._auth_header = f"Basic {b64_creds}"
            self.access_token = ""
        else:
            self.access_token = access_token
            self.base_url = (base_url or settings.JIRA_API_BASE_URL).rstrip("/")
            self._auth_header = f"Bearer {self.access_token}"

    async def __aenter__(self) -> "JiraClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": self._auth_header,
                    "Accept": "application/json",
                },
                timeout=25.0,
                follow_redirects=False,
            )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("JiraClient must be used as an async context manager.")
        return self._client

    def _api_url(self, cloud_id: str | None, path: str) -> str:
        rel = path.lstrip("/")
        if self.site_url:
            url = f"{self.site_url}/{rel}"
        else:
            if not cloud_id:
                raise JiraAPIError("Jira Cloud site ID is required.", status_code=409)
            url = f"{self.base_url}/ex/jira/{cloud_id}/{rel}"
        return validate_same_host_url(url, self.base_url)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        checked_url = validate_same_host_url(url, self.base_url)
        attempt = 0
        while True:
            try:
                response = await self.client.request(
                    method,
                    checked_url,
                    params=params,
                    json=json_body,
                    headers={
                        "Authorization": self._auth_header,
                        "Accept": "application/json",
                    },
                )
            except httpx.RequestError as exc:
                logger.warning("jira_request_network_error", error_type=type(exc).__name__)
                raise JiraAPIError("Network error communicating with Jira Cloud.") from exc

            if 300 <= response.status_code < 400:
                location = response.headers.get("Location") or ""
                if location:
                    # Verify same host; reject cross-host redirects
                    validate_same_host_url(location, self.base_url)
                raise JiraAPIError(
                    f"Jira API returned unexpected redirect (status {response.status_code}).",
                    status_code=502,
                )

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    logger.warning("jira_rate_limit_exhausted", attempts=attempt + 1)
                    raise JiraRateLimitError("Jira API rate limit exceeded.")
                retry_after_raw = response.headers.get("Retry-After")
                wait_seconds = _parse_retry_after(retry_after_raw, default=float(2**attempt))
                attempt += 1
                await asyncio.sleep(wait_seconds)
                continue

            return response

    async def get_me(self) -> dict[str, Any] | None:
        """Fetch the authenticated Atlassian user profile if read:me scope was granted."""
        if self.site_url:
            return await self.get_myself("")
        try:
            response = await self._request("GET", f"{self.base_url}/me")
            if response.status_code == 200:
                data = response.json()
                return cast(dict[str, Any], data) if isinstance(data, dict) else None
            return None
        except (JiraAPIError, ValueError):
            return None

    async def get_myself(self, cloud_id: str = "") -> dict[str, Any] | None:
        """Fetch the authenticated Jira user profile using the Jira Cloud instance."""
        try:
            url = self._api_url(cloud_id, "rest/api/3/myself")
            response = await self._request("GET", url)
            if response.status_code == 200:
                data = response.json()
                return cast(dict[str, Any], data) if isinstance(data, dict) else None
            return None
        except (JiraAPIError, ValueError):
            return None

    async def verify_myself(self, cloud_id: str = "") -> dict[str, Any]:
        """Fetch and strictly validate the authenticated Jira user profile (/rest/api/3/myself)."""
        url = self._api_url(cloud_id, "rest/api/3/myself")
        response = await self._request("GET", url)
        if response.status_code in (401, 403):
            raise JiraAPIError(
                "Jira rejected these credentials. Check your email and API token.",
                status_code=401,
            )
        if response.status_code != 200:
            raise JiraAPIError(
                f"Jira user verification failed with status {response.status_code}.",
                status_code=response.status_code if response.status_code < 500 else 502,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise JiraAPIError("Jira returned invalid JSON for user profile.") from exc
        if not isinstance(data, dict) or not (data.get("accountId") or data.get("account_id")):
            raise JiraAPIError("Jira returned an incomplete user profile.")
        return data

    async def get_accessible_resources(self) -> list[dict[str, Any]]:
        """Fetch Jira Cloud sites accessible to this authorization."""
        response = await self._request(
            "GET",
            f"{self.base_url}/oauth/token/accessible-resources",
        )
        if response.status_code != 200:
            raise JiraAPIError(
                f"Failed to fetch accessible Jira sites (status {response.status_code}).",
                status_code=response.status_code if response.status_code < 500 else 502,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise JiraAPIError("Jira returned invalid JSON for accessible resources.") from exc
        if not isinstance(data, list):
            raise JiraAPIError("Jira returned invalid accessible sites list.")
        return cast(list[dict[str, Any]], data)

    async def get_projects(self, cloud_id: str = "") -> list[dict[str, Any]]:
        """Fetch all projects from a specific Jira Cloud site with pagination."""
        projects: list[dict[str, Any]] = []
        start_at = 0
        max_results = 50
        pages = 0
        next_url: str | None = self._api_url(cloud_id, "rest/api/3/project/search")
        use_params = True

        while next_url and pages < 100:
            params: dict[str, Any] | None = (
                {"startAt": start_at, "maxResults": max_results} if use_params else None
            )
            response = await self._request("GET", next_url, params=params)
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to fetch Jira projects (status {response.status_code}).",
                    status_code=response.status_code if response.status_code < 500 else 502,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise JiraAPIError("Jira returned invalid JSON for projects.") from exc

            if not isinstance(data, dict):
                raise JiraAPIError("Jira returned an invalid projects response.")

            values = data.get("values", [])
            if not isinstance(values, list):
                raise JiraAPIError("Jira returned an invalid projects list.")
            projects.extend(v for v in values if isinstance(v, dict))
            pages += 1

            next_page_link = data.get("nextPage")
            is_last = data.get("isLast")
            total = data.get("total")

            if isinstance(next_page_link, str) and next_page_link:
                next_url = validate_same_host_url(next_page_link, self.base_url)
                use_params = False
            elif is_last is True or not values:
                next_url = None
            elif isinstance(total, int) and len(projects) < total:
                start_at += len(values)
            else:
                next_url = None

        return projects

    async def search_issues_jql(
        self,
        cloud_id: str = "",
        *,
        jql: str,
        fields: list[str] | None = None,
        expand: str | None = "changelog",
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Search issues using POST /rest/api/3/search/jql with nextPageToken pagination."""
        url = self._api_url(cloud_id, "rest/api/3/search/jql")
        requested_fields = fields or [
            "summary",
            "description",
            "status",
            "issuetype",
            "priority",
            "assignee",
            "reporter",
            "labels",
            "created",
            "updated",
            "comment",
        ]
        issues: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        next_page_token: str | None = None
        pages = 0

        while pages < 200:
            body: dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": requested_fields,
            }
            if expand:
                body["expand"] = expand
            if next_page_token:
                body["nextPageToken"] = next_page_token

            response = await self._request("POST", url, json_body=body)
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to query Jira issues (status {response.status_code}).",
                    status_code=response.status_code if response.status_code < 500 else 502,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise JiraAPIError("Jira returned invalid JSON for issue search.") from exc
            if not isinstance(data, dict):
                raise JiraAPIError("Jira returned invalid issue search payload.")

            page_issues = data.get("issues", [])
            if not isinstance(page_issues, list):
                raise JiraAPIError("Jira returned invalid issues array.")
            issues.extend(item for item in page_issues if isinstance(item, dict))
            pages += 1

            token = data.get("nextPageToken")
            is_last = data.get("isLast")
            if is_last is True or not isinstance(token, str) or not token:
                break
            if token in seen_tokens:
                raise JiraAPIError("Jira issue search pagination token did not advance.")
            seen_tokens.add(token)
            next_page_token = token

        return issues

    async def list_project_issue_ids(
        self,
        cloud_id: str = "",
        *,
        project_key: str,
        max_results: int = 100,
    ) -> set[str]:
        """Enumerate all current issue IDs in a Jira project via POST /rest/api/3/search/jql."""
        safe_key = project_key.replace('"', "")
        jql = f'project = "{safe_key}" ORDER BY created ASC'
        issues = await self.search_issues_jql(
            cloud_id,
            jql=jql,
            fields=["id"],
            expand=None,
            max_results=max_results,
        )
        issue_ids: set[str] = set()
        for item in issues:
            raw_id = item.get("id")
            if raw_id is not None and str(raw_id):
                issue_ids.add(str(raw_id))
        return issue_ids

    async def get_issue_comments(
        self,
        cloud_id: str = "",
        *,
        issue_id_or_key: str,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all comments for a single Jira issue with offset pagination."""
        url = self._api_url(cloud_id, f"rest/api/3/issue/{issue_id_or_key}/comment")
        comments: list[dict[str, Any]] = []
        start_at = 0
        pages = 0

        while pages < 100:
            response = await self._request(
                "GET",
                url,
                params={"startAt": start_at, "maxResults": max_results, "orderBy": "created"},
            )
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to fetch comments for Jira issue (status {response.status_code}).",
                    status_code=response.status_code if response.status_code < 500 else 502,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise JiraAPIError("Jira returned invalid JSON for issue comments.") from exc
            if not isinstance(data, dict):
                raise JiraAPIError("Jira returned invalid issue comments payload.")

            page_comments = data.get("comments", [])
            if not isinstance(page_comments, list):
                raise JiraAPIError("Jira returned invalid comments array.")
            valid_page = [c for c in page_comments if isinstance(c, dict)]
            comments.extend(valid_page)
            pages += 1

            total = data.get("total")
            if not valid_page:
                break
            start_at += len(valid_page)
            if isinstance(total, int) and start_at >= total:
                break
            if not isinstance(total, int) and len(valid_page) < max_results:
                break

        return comments

    async def get_issue_changelog(
        self,
        cloud_id: str = "",
        *,
        issue_id_or_key: str,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all changelog history entries for a single Jira issue with pagination."""
        next_url: str | None = self._api_url(
            cloud_id, f"rest/api/3/issue/{issue_id_or_key}/changelog"
        )
        histories: list[dict[str, Any]] = []
        start_at = 0
        pages = 0
        use_params = True

        while next_url and pages < 100:
            params: dict[str, Any] | None = (
                {"startAt": start_at, "maxResults": max_results} if use_params else None
            )
            response = await self._request("GET", next_url, params=params)
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to fetch changelog for Jira issue (status {response.status_code}).",
                    status_code=response.status_code if response.status_code < 500 else 502,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise JiraAPIError("Jira returned invalid JSON for issue changelog.") from exc
            if not isinstance(data, dict):
                raise JiraAPIError("Jira returned invalid issue changelog payload.")

            values = data.get("values")
            if not isinstance(values, list):
                values = data.get("histories", [])
            if not isinstance(values, list):
                raise JiraAPIError("Jira returned invalid changelog histories array.")
            valid_page = [h for h in values if isinstance(h, dict)]
            histories.extend(valid_page)
            pages += 1

            next_page_link = data.get("nextPage")
            is_last = data.get("isLast")
            total = data.get("total")

            if isinstance(next_page_link, str) and next_page_link:
                next_url = validate_same_host_url(next_page_link, self.base_url)
                use_params = False
            elif is_last is True or not valid_page:
                next_url = None
            elif isinstance(total, int) and len(histories) < total:
                start_at += len(valid_page)
            else:
                next_url = None

        return histories


def _parse_retry_after(header_value: str | None, *, default: float = 1.0) -> float:
    if not header_value:
        return default
    try:
        parsed = float(header_value.strip())
        return min(max(parsed, 0.0), 60.0)
    except ValueError:
        return default

