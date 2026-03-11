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
import time
from abc import ABC, abstractmethod
from typing import TypeVar

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from prometheus_client import Counter, Histogram
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM observability metrics (Item 7)
# Defined at module level so the prometheus_client registry deduplicates them
# correctly across multiple imports.
# ---------------------------------------------------------------------------
_LLM_LATENCY = Histogram(
    "llm_call_duration_seconds",
    "LLM API call latency in seconds",
    ["provider", "model", "cached"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

_LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["provider", "model", "token_type"],
)

_LLM_ERRORS = Counter(
    "llm_errors_total",
    "Total LLM API call errors",
    ["provider", "model"],
)

T = TypeVar("T", bound=BaseModel)

# Regex to extract JSON from markdown code blocks (```json ... ``` or ``` ... ```)
# Also handles bare JSON (no code block) by falling through to raw content.
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _extract_first_json_object(text: str) -> str | None:
    """
    Extract the first complete JSON object from text using bracket counting.

    Handles preamble text before the JSON and trailing text after it.
    Correctly handles arbitrarily nested objects — greedy regex cannot do this
    because `{.*}` with DOTALL grabs from the first `{` to the *last* `}`,
    mangling nested structures and any JSON that appears after the first object.
    """
    depth = 0
    start: int | None = None
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : i + 1]

    return None


def extract_json_from_llm_response(content: str) -> str:
    """
    Extract JSON from an LLM response that may be wrapped in markdown code blocks
    or preceded by preamble text.

    Handles (in priority order):
    1. ```json { ... } ``` — markdown JSON code block
    2. ``` { ... } ```    — generic code block
    3. Bare JSON with preamble (e.g. "Here is the JSON:\n{...}")
    4. Raw JSON with no surrounding text
    """
    content = content.strip()

    # Priority 1 & 2: extract from markdown code block
    match = _CODE_BLOCK_RE.search(content)
    if match:
        return match.group(1).strip()

    # Priority 3 & 4: find the first complete JSON object via bracket counting.
    # This handles "Here is the output:\n{...}" and plain "{...}" equally.
    extracted = _extract_first_json_object(content)
    if extracted:
        return extracted

    # Last resort — return as-is and let the caller's JSON parser report the error
    return content


class LLMResponse(BaseModel):
    """Standard LLM response with metadata."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


class LLMCache:
    """Redis-backed semantic cache for LLM responses.

    Uses the application-wide shared Redis pool from app.core.redis so no
    separate connection pool is created per feature. The pool lifecycle
    (connect / close) is managed entirely by main.py lifespan.
    """

    def _generate_key(self, prompt: str, model: str, temperature: float) -> str:
        """Generate a deterministic cache key."""
        key_content = f"{model}:{temperature}:{prompt.strip()}"
        return f"llm_cache:{hashlib.sha256(key_content.encode()).hexdigest()}"

    async def get(self, prompt: str, model: str, temperature: float) -> LLMResponse | None:
        """Retrieve cached response if available."""
        try:
            key = self._generate_key(prompt, model, temperature)
            cached_json = await get_redis().get(key)
            if cached_json:
                logger.info(f"LLM Cache Hit: {key}")
                return LLMResponse(**json.loads(cached_json))
            return None
        except Exception as e:
            logger.warning(f"LLM Cache read error: {e}")
            return None

    async def set(self, prompt: str, model: str, temperature: float, response: LLMResponse):
        """Cache response with TTL."""
        try:
            key = self._generate_key(prompt, model, temperature)
            await get_redis().setex(key, settings.redis_cache_ttl, response.model_dump_json())
        except Exception as e:
            logger.warning(f"LLM Cache write error: {e}")


# Global cache instance
llm_cache = LLMCache()


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    model: str
    temperature: float

    @abstractmethod
    async def _generate_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Internal method to generate text completion without cache."""
        pass

    # NEW-15: skip cache for high-temperature (creative) calls. At temp > 0.5 the
    # caller explicitly wants non-deterministic output; caching would return the
    # same response every time, defeating the purpose (e.g. AI incident generator).
    _HIGH_TEMP_CACHE_THRESHOLD = 0.5

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        use_cache: bool = True,
    ) -> LLMResponse:
        """Generate text completion with caching and Prometheus instrumentation."""
        # Resolve defaults
        temp = temperature if temperature is not None else self.temperature

        # Include system prompt in cache key so different system prompts don't collide
        cache_prompt_key = f"{system_prompt or ''}::{prompt}"

        # Skip cache for high-temperature creative calls (temp > 0.5)
        should_cache = use_cache and temp <= self._HIGH_TEMP_CACHE_THRESHOLD

        # Derive a short provider name from the concrete class name for labels
        provider = type(self).__name__.replace("Client", "").lower()

        if should_cache:
            cached = await llm_cache.get(cache_prompt_key, self.model, temp)
            if cached:
                _LLM_LATENCY.labels(provider=provider, model=self.model, cached="true").observe(0)
                _LLM_TOKENS.labels(provider=provider, model=self.model, token_type="prompt").inc(cached.prompt_tokens)
                _LLM_TOKENS.labels(provider=provider, model=self.model, token_type="completion").inc(cached.completion_tokens)
                return cached

        # Generate fresh and measure wall-clock latency
        t0 = time.perf_counter()
        try:
            response = await self._generate_raw(prompt, system_prompt, temperature, max_tokens)
        except Exception:
            _LLM_ERRORS.labels(provider=provider, model=self.model).inc()
            raise
        elapsed = time.perf_counter() - t0

        _LLM_LATENCY.labels(provider=provider, model=self.model, cached="false").observe(elapsed)
        _LLM_TOKENS.labels(provider=provider, model=self.model, token_type="prompt").inc(response.prompt_tokens)
        _LLM_TOKENS.labels(provider=provider, model=self.model, token_type="completion").inc(response.completion_tokens)

        if should_cache:
            await llm_cache.set(cache_prompt_key, self.model, temp, response)

        return response

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str | None = None,
        temperature: float | None = None,
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
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate text completion with Claude."""
        try:
            messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]

            # NEW-18 fix: use explicit None check — `temperature or self.temperature`
            # treats 0.0 (fully deterministic) as falsy and falls back to default.
            effective_temp = temperature if temperature is not None else self.temperature
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                temperature=effective_temp,
                system=system_prompt or "",
                messages=messages,  # type: ignore[arg-type]
            )

            content = next((block.text for block in response.content if hasattr(block, "text")), "")

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
        response_model: type[T],
        system_prompt: str | None = None,
        temperature: float | None = None,
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
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate text completion with GPT."""
        try:
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # NEW-18 fix: explicit None check — 0.0 is falsy in Python.
            effective_temp = temperature if temperature is not None else self.temperature
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=effective_temp,
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
        response_model: type[T],
        system_prompt: str | None = None,
        temperature: float | None = None,
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
    # NEW-30 fix: removed dead generate() override that only called super().generate().
    # If OpenRouter-specific headers are needed in the future (e.g. HTTP-Referer),
    # override _generate_raw() instead — that's the correct extension point.


def get_llm_client(model: str | None = None) -> LLMClient:
    """
    Factory function to get the configured LLM client.

    Args:
        model: Optional model override. If None, uses settings.llm_model.
               Pass settings.llm_generator_model to get a generator-specific
               client without mutating the returned instance (NEW-10 fix).

    Supported providers:
    - anthropic: Claude models (paid)
    - openai: GPT models (paid) or Groq keys (gsk_... auto-detected)
    - openrouter: Access to multiple models including free options
    - groq: Fast inference with Llama/Mixtral (free tier available)
    """
    effective_model = model or settings.llm_model

    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key.get_secret_value():
            raise ValueError("ANTHROPIC_API_KEY not configured (set AIRRA_ANTHROPIC_API_KEY)")
        return AnthropicClient(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=effective_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "openai":
        if not settings.openai_api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY not configured (set AIRRA_OPENAI_API_KEY)")
        return OpenAIClient(
            api_key=settings.openai_api_key.get_secret_value(),
            model=effective_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "groq":
        # NEW-14 fix: prefer the dedicated groq_api_key; fall back to openai_api_key
        # for backwards compatibility with deployments using the legacy env var.
        groq_key = settings.groq_api_key.get_secret_value() or settings.openai_api_key.get_secret_value()
        if not groq_key:
            raise ValueError(
                "Groq API key not configured. Set AIRRA_GROQ_API_KEY "
                "(or AIRRA_OPENAI_API_KEY for legacy compatibility)."
            )
        return OpenAIClient(
            api_key=groq_key,
            model=effective_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key.get_secret_value():
            raise ValueError("OPENROUTER_API_KEY not configured (set AIRRA_OPENROUTER_API_KEY)")
        return OpenRouterClient(
            api_key=settings.openrouter_api_key.get_secret_value(),
            model=effective_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
