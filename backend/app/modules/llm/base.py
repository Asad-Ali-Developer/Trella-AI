"""LLM Provider abstraction, results, and interfaces."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class LLMResult(BaseModel):
    """Normalized output from any LLM provider."""

    content: str
    parsed: Any | None = None
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    model: str
    provider: str
    raw_response: dict[str, Any] = Field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract interface for LLM providers (Gemini, OpenAI, etc.)."""

    provider_name: str

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> LLMResult:
        """Generate unstructured text response."""
        pass

    @abstractmethod
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
        """Generate response strictly conforming to a Pydantic schema."""
        pass
