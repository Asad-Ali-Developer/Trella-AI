from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class TrelloAPIError(Exception):
    """Trello rejected a request or returned an unexpected response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class TrelloServerError(TrelloAPIError):
    """Trello returned a retryable server error."""


class TrelloRateLimitError(TrelloAPIError):
    """Trello rate limit was exceeded."""


class TrelloClient:
    """Async Trello API client with bounded retries for transient failures."""

    def __init__(
        self,
        token: str,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.trello.com/1",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.token = token
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def __aenter__(self) -> "TrelloClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_member(self) -> dict[str, Any]:
        """Validate credentials and return the connected Trello account."""
        payload = await self._get("/members/me", params={"fields": "id,username,fullName"})
        if not isinstance(payload, dict):
            raise TrelloAPIError(502, "Trello returned an invalid member response.")
        return payload

    async def list_boards(self) -> list[dict[str, Any]]:
        """Return open boards visible to the connected Trello account."""
        payload = await self._get(
            "/members/me/boards",
            params={"filter": "open", "fields": "id,name,url,closed"},
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise TrelloAPIError(502, "Trello returned an invalid boards response.")
        return payload

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, TrelloServerError)
        ),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _get(self, path: str, *, params: Mapping[str, str]) -> Any:
        request_options: dict[str, Any] = {}
        if self.api_key:
            request_options["params"] = {**params, "key": self.api_key, "token": self.token}
        else:
            request_options["params"] = params
            request_options["headers"] = {"Authorization": f"Bearer {self.token}"}
        response = await self._client.get(path, **request_options)
        if response.status_code == 429:
            raise TrelloRateLimitError(429, "Trello API rate limit exceeded.")
        if response.status_code >= 500:
            raise TrelloServerError(response.status_code, "Trello API is temporarily unavailable.")
        if response.is_error:
            raise TrelloAPIError(response.status_code, "Trello rejected the request.")
        try:
            return response.json()
        except ValueError as exc:
            raise TrelloAPIError(502, "Trello returned invalid JSON.") from exc
