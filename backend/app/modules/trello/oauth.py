from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class TrelloOAuthError(Exception):
    """Trello OAuth rejected a request or returned invalid token data."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class TrelloOAuthTokens(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    expires_in: int = Field(gt=0)
    token_type: str = "Bearer"
    scope: str | None = None


class TrelloOAuthClient:
    """Confidential OAuth client for Trello's authorization-code flow."""

    token_url = "https://auth.atlassian.com/oauth/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def __aenter__(self) -> "TrelloOAuthClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> TrelloOAuthTokens:
        return await self._request_tokens(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> TrelloOAuthTokens:
        return await self._request_tokens(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _request_tokens(self, grant: dict[str, str]) -> TrelloOAuthTokens:
        response = await self._client.post(
            self.token_url,
            json={
                **grant,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/json"},
        )
        if response.is_error:
            status_code = 400 if response.status_code in {400, 401, 403} else 502
            raise TrelloOAuthError("Trello authorization could not be completed.", status_code)
        try:
            data: Any = response.json()
            return TrelloOAuthTokens.model_validate(data)
        except (ValueError, TypeError) as exc:
            raise TrelloOAuthError("Trello returned invalid token data.") from exc
