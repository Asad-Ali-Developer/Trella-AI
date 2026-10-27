from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.modules.trello.rate_limiter import TrelloRateLimiter


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
        rate_limiter: TrelloRateLimiter | None = None,
    ) -> None:
        self.api_key = api_key
        self.token = token
        self.rate_limiter = rate_limiter
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

    async def list_board_cards(self, board_id: str) -> list[dict[str, Any]]:
        """Fetch board cards in bounded pages, including archived cards."""
        cards: list[dict[str, Any]] = []
        seen: set[str] = set()
        before: str | None = None
        while True:
            params = {
                "filter": "all",
                "fields": ("id,name,desc,idList,idMembers,dateLastActivity,due,closed,url,labels"),
                "limit": "1000",
            }
            if before:
                params["before"] = before
            payload = await self._get(f"/boards/{board_id}/cards", params=params)
            if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                raise TrelloAPIError(502, "Trello returned an invalid cards response.")
            page = [item for item in payload if isinstance(item.get("id"), str)]
            fresh = [item for item in page if item["id"] not in seen]
            if page and not fresh:
                raise TrelloAPIError(502, "Trello card pagination did not advance.")
            cards.extend(fresh)
            seen.update(item["id"] for item in fresh)
            if len(page) < 1000:
                return cards
            before = str(page[-1].get("dateLastActivity", ""))
            if not before:
                raise TrelloAPIError(502, "Trello card pagination returned no activity cursor.")

    async def list_board_lists(self, board_id: str) -> list[dict[str, Any]]:
        payload = await self._get(
            f"/boards/{board_id}/lists",
            params={"filter": "all", "fields": "id,name,closed"},
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise TrelloAPIError(502, "Trello returned an invalid lists response.")
        return payload

    async def get_board(self, board_id: str) -> dict[str, Any]:
        payload = await self._get(
            f"/boards/{board_id}",
            params={"fields": "id,name"},
        )
        if not isinstance(payload, dict):
            raise TrelloAPIError(502, "Trello returned an invalid board response.")
        return payload

    async def list_board_members(self, board_id: str) -> list[dict[str, Any]]:
        payload = await self._get(
            f"/boards/{board_id}/members",
            params={"fields": "id,username,fullName"},
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise TrelloAPIError(502, "Trello returned an invalid members response.")
        return payload

    async def list_board_comments(self, board_id: str) -> list[dict[str, Any]]:
        """Fetch comment actions in pages without expanding actions on card responses."""
        actions: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_number = 0
        while True:
            params = {
                "filter": "commentCard",
                "limit": "1000",
                "page": str(page_number),
            }
            payload = await self._get(f"/boards/{board_id}/actions", params=params)
            if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                raise TrelloAPIError(502, "Trello returned an invalid comments response.")
            page = [item for item in payload if isinstance(item.get("id"), str)]
            fresh = [item for item in page if item["id"] not in seen]
            if page and not fresh:
                raise TrelloAPIError(502, "Trello action pagination did not advance.")
            actions.extend(fresh)
            seen.update(item["id"] for item in fresh)
            if len(page) < 1000:
                return actions
            page_number += 1

    async def create_board_webhook(self, board_id: str, callback_url: str) -> dict[str, Any]:
        request_options: dict[str, Any] = {
            "json": {
                "description": "Trella board sync",
                "callbackURL": callback_url,
                "idModel": board_id,
            }
        }
        if self.api_key:
            request_options["params"] = {"key": self.api_key, "token": self.token}
            path = f"/tokens/{self.token}/webhooks"
        else:
            request_options["headers"] = {"Authorization": f"Bearer {self.token}"}
            path = "/webhooks"
        response = await self._post(path, **request_options)
        if not isinstance(response, dict) or not isinstance(response.get("id"), str):
            raise TrelloAPIError(502, "Trello returned an invalid webhook response.")
        return response

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.NetworkError, TrelloServerError)
        ),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _get(self, path: str, *, params: Mapping[str, str]) -> Any:
        if self.rate_limiter:
            await self.rate_limiter.acquire(self.api_key or "oauth", self.token, path)
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

    async def _post(self, path: str, **request_options: Any) -> Any:
        if self.rate_limiter:
            await self.rate_limiter.acquire(self.api_key or "oauth", self.token, path)
        if self.api_key:
            request_options["params"] = {
                **request_options.get("params", {}),
                "key": self.api_key,
                "token": self.token,
            }
        response = await self._client.post(path, **request_options)
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
