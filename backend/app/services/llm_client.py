"""
LLM Client for hypothesis generation and reasoning.

Senior Engineering Note:
- Abstraction layer over different LLM providers
- Structured output parsing
- Token usage tracking
- Retry logic with exponential backoff
"""
import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Optional, Type, TypeVar

import redis.asyncio as redis
from anthropic import Anthropic, AsyncAnthropic
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex to extract JSON from markdown code blocks (```json ... ``` or ``` ... ```)
# Also handles bare JSON (no code block) by falling through to raw content.
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def extract_json_from_llm_response(content: str) -> str:
    """
    Extract JSON from an LLM response that may be wrapped in markdown code blocks.

    Handles:
    - ```json { ... } ```
    - ``` { ... } ```
    - Bare JSON with no code block
    - Multiple code blocks (takes the first one)
    """
    content = content.strip()
    match = _CODE_BLOCK_RE.search(content)
    if match:
        return match.group(1).strip()
    # No code block found — assume the content is raw JSON
    return content


class LLMResponse(BaseModel):
    """Standard LLM response with metadata."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


class LLMCache:
    """Redis-based semantic cache for LLM responses."""

    def __init__(self):
        self._redis: redis.Redis | None = None

    async def get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(str(settings.redis_url), encoding="utf-8", decode_responses=True)
        return self._redis

    async def close(self):
        """Close the Redis connection and release resources."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("LLM cache Redis connection closed")

    def _generate_key(self, prompt: str, model: str, temperature: float) -> str:
        """Generate a deterministic cache key."""
        # Normalize inputs
        key_content = f"{model}:{temperature}:{prompt.strip()}"
        return f"llm_cache:{hashlib.sha256(key_content.encode()).hexdigest()}"

    async def get(self, prompt: str, model: str, temperature: float) -> LLMResponse | None:
        """Retrieve cached response if available."""
        try:
            r = await self.get_redis()
            key = self._generate_key(prompt, model, temperature)
            cached_json = await r.get(key)
            
            if cached_json:
                logger.info(f"LLM Cache Hit: {key}")
                data = json.loads(cached_json)
                return LLMResponse(**data)
            return None
        except Exception as e:
            logger.warning(f"LLM Cache read error: {e}")
            return None

    async def set(self, prompt: str, model: str, temperature: float, response: LLMResponse):
        """Cache response with TTL."""
        try:
            r = await self.get_redis()
            key = self._generate_key(prompt, model, temperature)
            # Use configurated TTL or default to 24 hours (86400 seconds)
            ttl = getattr(settings, "llm_cache_ttl", 86400)
            await r.setex(key, ttl, response.model_dump_json())
        except Exception as e:
            logger.warning(f"LLM Cache write error: {e}")


# Global cache instance
llm_cache = LLMCache()


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def _generate_raw(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Internal method to generate text completion without cache."""
        pass

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate text completion with caching."""
        # Resolve defaults
        temp = temperature if temperature is not None else self.temperature
        
        # Try cache first (only if no system prompt for now, or include system prompt in key)
        # Note: We'll include system prompt in the key by appending it to the prompt for hashing
        cache_prompt_key = f"{system_prompt or ''}::{prompt}"
        
        cached = await llm_cache.get(cache_prompt_key, self.model, temp)
        if cached:
            return cached

        # Generate fresh
        response = await self._generate_raw(prompt, system_prompt, temperature, max_tokens)

        # Cache result
        await llm_cache.set(cache_prompt_key, self.model, temp, response)
        
        return response

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> tuple[T, LLMResponse]:
        """Generate structured output conforming to a Pydantic model."""
        pass


class AnthropicClient(LLMClient):
    """Claude API client with async support."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    async def _generate_raw(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate text completion with Claude."""
        try:
            messages = [{"role": "user", "content": prompt}]

            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature or self.temperature,
                system=system_prompt or "",
                messages=messages,
            )

            content = response.content[0].text

            return LLMResponse(
                content=content,
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                model=self.model,
            )

        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            raise

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> tuple[T, LLMResponse]:
        """
        Generate structured output conforming to a Pydantic model.

        Uses JSON schema in the prompt to guide the model.
        """
        # Create JSON schema from Pydantic model
        schema = response_model.model_json_schema()

        # Enhance prompt with schema
        enhanced_prompt = f"""
{prompt}

You must respond with valid JSON that conforms to this schema:

{json.dumps(schema, indent=2)}

Respond ONLY with the JSON object, no additional text.
"""

        # Get response (this uses generate() which handles caching)
        llm_response = await self.generate(
            prompt=enhanced_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )

        # Parse JSON response
        try:
            content = extract_json_from_llm_response(llm_response.content)
            parsed_response = response_model.model_validate_json(content)
            return parsed_response, llm_response

        except Exception as e:
            logger.error(f"Failed to parse structured response: {str(e)}")
            logger.error(f"Raw content: {llm_response.content}")
            raise ValueError(f"Invalid JSON response from LLM: {str(e)}")


class OpenAIClient(LLMClient):
    """OpenAI GPT client with async support. Also supports Groq (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        base_url: str | None = None,
    ):
        # Support Groq by detecting Groq API keys and using their base URL
        if api_key.startswith("gsk_"):
            base_url = "https://api.groq.com/openai/v1"

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    async def _generate_raw(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate text completion with GPT."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
            )

            content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                model=self.model,
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> tuple[T, LLMResponse]:
        """Generate structured output using OpenAI's JSON mode."""
        schema = response_model.model_json_schema()

        enhanced_prompt = f"""
{prompt}

Respond with valid JSON conforming to this schema:
{json.dumps(schema, indent=2)}
"""

        # Uses generate() which handles caching
        llm_response = await self.generate(
            prompt=enhanced_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )

        try:
            content = extract_json_from_llm_response(llm_response.content)
            parsed_response = response_model.model_validate_json(content)
            return parsed_response, llm_response

        except Exception as e:
            logger.error(f"Failed to parse structured response: {str(e)}")
            raise ValueError(f"Invalid JSON response from LLM: {str(e)}")


class OpenRouterClient(OpenAIClient):
    """OpenRouter client (OpenAI compatible)."""

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-3.5-sonnet",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        # OpenRouter is compatible with OpenAI API
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate text completion with OpenRouter."""
        # We can add OpenRouter specific headers if needed
        # extra_headers={
        #     "HTTP-Referer": "https://airra.ai",
        #     "X-Title": "AIRRA",
        # }
        return await super().generate(prompt, system_prompt, temperature, max_tokens)


def get_llm_client() -> LLMClient:
    """
    Factory function to get the configured LLM client.

    Returns the appropriate client based on settings.

    Supported providers:
    - anthropic: Claude models (paid)
    - openai: GPT models (paid) or Groq (free, use openai provider)
    - openrouter: Access to multiple models including free options
    - groq: Fast inference with Llama/Mixtral (free)
    """
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key.get_secret_value():
            raise ValueError("ANTHROPIC_API_KEY not configured")
        return AnthropicClient(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "openai":
        if not settings.openai_api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY not configured")
        return OpenAIClient(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "groq":
        if not settings.openai_api_key.get_secret_value():
            raise ValueError("GROQ_API_KEY not configured (use AIRRA_OPENAI_API_KEY)")
        # Groq uses OpenAI-compatible API
        return OpenAIClient(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key.get_secret_value():
            raise ValueError("OPENROUTER_API_KEY not configured")
        return OpenRouterClient(
            api_key=settings.openrouter_api_key.get_secret_value(),
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
