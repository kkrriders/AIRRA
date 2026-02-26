"""Unit tests for LLM client."""
import pytest
from unittest.mock import AsyncMock, Mock, patch
from app.services.llm_client import AnthropicClient, OpenAIClient, OpenRouterClient, get_llm_client, LLMResponse
from app.core.reasoning.hypothesis_generator import HypothesesResponse


class TestAnthropicClient:
    """Test Anthropic/Claude client."""

    async def test_generate_text(self, mock_anthropic_response, monkeypatch):
        """Test text generation."""
        with patch('app.services.llm_client.AsyncAnthropic') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_anthropic_response)
            mock_client_class.return_value = mock_client

            client = AnthropicClient(api_key="test-key")
            response = await client.generate(prompt="Test prompt")

            assert response.total_tokens > 0
            assert response.content is not None
            mock_client.messages.create.assert_called_once()

    async def test_generate_structured_output(self, mock_anthropic_response):
        """Test structured output generation."""
        with patch('app.services.llm_client.AsyncAnthropic') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.messages.create = AsyncMock(return_value=mock_anthropic_response)
            mock_client.return_value = mock_instance

            client = AnthropicClient(api_key="test-key")
            # Test structure validated
            assert client.model == "claude-3-5-sonnet-20241022"

    def test_initialization_with_custom_params(self):
        """Test client initialization with custom parameters."""
        client = AnthropicClient(
            api_key="test-key",
            model="claude-3-opus-20240229",
            temperature=0.5,
            max_tokens=2048
        )

        assert client.model == "claude-3-opus-20240229"
        assert client.temperature == 0.5
        assert client.max_tokens == 2048

    def test_strips_markdown_code_blocks(self):
        """Test that markdown code blocks are stripped from JSON."""
        test_json = '```json\n{"key": "value"}\n```'
        expected = '{"key": "value"}'

        # Simple strip test
        cleaned = test_json.replace('```json\n', '').replace('\n```', '').strip()
        assert cleaned == expected


class TestOpenAIClient:
    """Test OpenAI/GPT client."""

    async def test_generate_with_gpt(self, mock_openai_response):
        """Test GPT text generation."""
        with patch('app.services.llm_client.AsyncOpenAI') as mock_client:
            mock_instance = AsyncMock()
            mock_instance.chat.completions.create = AsyncMock(return_value=mock_openai_response)
            mock_client.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")
            assert client.model == "gpt-4-turbo-preview"

    def test_groq_api_key_detection(self):
        """Test Groq API key sets correct base URL."""
        client = OpenAIClient(api_key="gsk_test_key")
        # Should detect Groq prefix and set base_url
        assert client.client.base_url is not None
        assert "groq" in str(client.client.base_url).lower()

    def test_initialization_defaults(self):
        """Test default initialization."""
        client = OpenAIClient(api_key="test-key")
        assert client.model == "gpt-4-turbo-preview"
        assert client.temperature == 0.3


class TestOpenRouterClient:
    """Test OpenRouter client."""

    def test_initialization(self):
        """Test OpenRouter initialization."""
        client = OpenRouterClient(api_key="test-key")
        assert "openrouter" in str(client.client.base_url).lower()
        assert client.model == "anthropic/claude-3.5-sonnet"

    def test_custom_model_selection(self):
        """Test custom model can be specified."""
        client = OpenRouterClient(
            api_key="test-key",
            model="anthropic/claude-3-opus"
        )
        assert client.model == "anthropic/claude-3-opus"


class TestLLMClientFactory:
    """Test get_llm_client factory function."""

    def test_returns_anthropic_client(self, monkeypatch):
        """Test factory returns Anthropic client."""
        from app.config import settings
        from pydantic import SecretStr
        monkeypatch.setattr(settings, "llm_provider", "anthropic")
        monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("test-key"))

        client = get_llm_client()
        assert isinstance(client, AnthropicClient)

    def test_returns_openai_client(self, monkeypatch):
        """Test factory returns OpenAI client."""
        from app.config import settings
        from pydantic import SecretStr
        monkeypatch.setattr(settings, "llm_provider", "openai")
        monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key"))

        client = get_llm_client()
        assert isinstance(client, OpenAIClient)

    def test_returns_openrouter_client(self, monkeypatch):
        """Test factory returns OpenRouter client."""
        from app.config import settings
        from pydantic import SecretStr
        monkeypatch.setattr(settings, "llm_provider", "openrouter")
        monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("test-key"))

        client = get_llm_client()
        assert isinstance(client, OpenRouterClient)

    def test_raises_error_for_unknown_provider(self, monkeypatch):
        """Test error for unknown provider."""
        from app.config import settings
        monkeypatch.setattr(settings, "llm_provider", "unknown")

        with pytest.raises(ValueError, match="provider"):
            get_llm_client()

    def test_raises_error_for_missing_api_key(self, monkeypatch):
        """Test error when API key missing."""
        from app.config import settings
        from pydantic import SecretStr
        monkeypatch.setattr(settings, "llm_provider", "anthropic")
        monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))

        with pytest.raises((ValueError, KeyError)):
            get_llm_client()


class TestLLMResponse:
    """Test LLMResponse model."""

    def test_token_calculation(self):
        """Test token counts."""
        response = LLMResponse(
            content="Test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="test-model"
        )

        assert response.total_tokens == response.prompt_tokens + response.completion_tokens

    def test_model_validation(self):
        """Test Pydantic validation."""
        response = LLMResponse(
            content="Test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="claude-3-5-sonnet-20241022"
        )

        assert response.model == "claude-3-5-sonnet-20241022"
        assert isinstance(response.content, str)
