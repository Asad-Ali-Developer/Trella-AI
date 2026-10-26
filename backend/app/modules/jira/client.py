"""HTTP Client and OAuth handling for Jira Cloud via Atlassian OAuth 2.0 (3LO)."""

from typing import Any
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.modules.jira.client")


class JiraAPIError(Exception):
    """Exception raised when Jira or Atlassian API requests fail."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.post(
                    f"{self.auth_url}/oauth/token",
                    json=payload,
                )
                if response.status_code != 200:
                    logger.error(
                        "jira_token_exchange_failed",
                        status_code=response.status_code,
                        detail=response.text,
                    )
                    raise JiraAPIError(
                        f"Atlassian rejected authorization code ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                    )
                return JiraOAuthTokens.model_validate(response.json())
            except httpx.RequestError as exc:
                logger.error("jira_token_exchange_request_error", error=str(exc))
                raise JiraAPIError(f"Network error contacting Atlassian OAuth: {exc}") from exc

    async def refresh_tokens(self, refresh_token: str) -> JiraOAuthTokens:
        """Refresh expired access token using the refresh token."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.post(
                    f"{self.auth_url}/oauth/token",
                    json=payload,
                )
                if response.status_code != 200:
                    logger.error(
                        "jira_token_refresh_failed",
                        status_code=response.status_code,
                        detail=response.text,
                    )
                    raise JiraAPIError(
                        f"Failed to refresh Jira authorization: {response.text}",
                        status_code=response.status_code,
                    )
                return JiraOAuthTokens.model_validate(response.json())
            except httpx.RequestError as exc:
                raise JiraAPIError(f"Network error refreshing Jira tokens: {exc}") from exc


class JiraClient:
    """Authenticated client for Jira Cloud REST API."""

    def __init__(
        self,
        access_token: str,
        base_url: str | None = None,
    ) -> None:
        self.access_token = access_token
        self.base_url = (base_url or settings.JIRA_API_BASE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "JiraClient":
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
            timeout=25.0,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("JiraClient must be used as an async context manager.")
        return self._client

    async def get_me(self) -> dict[str, Any] | None:
        """Fetch the authenticated Atlassian user profile if read:me scope was granted."""
        try:
            response = await self.client.get(f"{self.base_url}/me")
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.RequestError:
            return None

    async def get_myself(self, cloud_id: str) -> dict[str, Any] | None:
        """Fetch the authenticated Jira user profile using the Jira Cloud instance."""
        try:
            response = await self.client.get(
                f"{self.base_url}/ex/jira/{cloud_id}/rest/api/3/myself"
            )
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.RequestError:
            return None


    async def get_accessible_resources(self) -> list[dict[str, Any]]:
        """Fetch Jira Cloud sites accessible to this authorization."""
        try:
            response = await self.client.get(
                f"{self.base_url}/oauth/token/accessible-resources"
            )
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to fetch accessible Jira sites ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                )
            return response.json()
        except httpx.RequestError as exc:
            raise JiraAPIError(f"Network error fetching Jira sites: {exc}") from exc

    async def get_projects(self, cloud_id: str) -> list[dict[str, Any]]:
        """Fetch projects from a specific Jira Cloud site."""
        try:
            response = await self.client.get(
                f"{self.base_url}/ex/jira/{cloud_id}/rest/api/3/project/search"
            )
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to fetch Jira projects ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                )
            data = response.json()
            # Jira returns { "values": [...] }
            return data.get("values", [])
        except httpx.RequestError as exc:
            raise JiraAPIError(f"Network error fetching Jira projects: {exc}") from exc

    async def get_issues(
        self,
        cloud_id: str,
        *,
        jql: str = "",
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Search issues in a specific Jira Cloud site using JQL."""
        try:
            params: dict[str, Any] = {"maxResults": max_results}
            if jql:
                params["jql"] = jql
            response = await self.client.get(
                f"{self.base_url}/ex/jira/{cloud_id}/rest/api/3/search",
                params=params,
            )
            if response.status_code != 200:
                raise JiraAPIError(
                    f"Failed to query Jira issues ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                )
            return response.json().get("issues", [])
        except httpx.RequestError as exc:
            raise JiraAPIError(f"Network error querying Jira issues: {exc}") from exc
