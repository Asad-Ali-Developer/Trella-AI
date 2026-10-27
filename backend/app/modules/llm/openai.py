"""OpenAI LLM provider adapter (interface stub for Phase 4 extension)."""

from typing import TypeVar
from fastapi import HTTPException, status
from pydantic import BaseModel

from app.modules.llm.base import LLMProvider, LLMResult

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider implementing LLMProvider interface."""

    provider_name = "openai"

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model = model

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> LLMResult:
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="OpenAI provider is not yet configured. Set OPENAI_API_KEY in .env.",
            )
        raise NotImplementedError("OpenAI provider integration will be enabled in future update.")

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> tuple[T, LLMResult]:
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="OpenAI provider is not yet configured. Set OPENAI_API_KEY in .env.",
            )
        raise NotImplementedError("OpenAI provider integration will be enabled in future update.")
