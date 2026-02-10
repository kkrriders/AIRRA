import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm_client import LLMCache, LLMResponse, LLMClient

@pytest.mark.asyncio
async def test_llm_cache_key_generation():
    cache = LLMCache()
    key1 = cache._generate_key("Hello world", "gpt-4", 0.5)
    key2 = cache._generate_key("Hello world", "gpt-4", 0.5)
    key3 = cache._generate_key("Hello world", "gpt-3.5", 0.5)
    
    assert key1 == key2
    assert key1 != key3
    assert key1.startswith("llm_cache:")

@pytest.mark.asyncio
async def test_llm_cache_hit_miss():
    # Mock Redis
    mock_redis = AsyncMock()
    
    # Setup cache with mocked redis
    cache = LLMCache()
    cache._redis = mock_redis
    
    # Test Miss
    mock_redis.get.return_value = None
    result = await cache.get("prompt", "model", 0.1)
    assert result is None
    
    # Test Hit
    cached_response = LLMResponse(
        content="Cached content",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        model="model"
    )
    mock_redis.get.return_value = cached_response.model_dump_json()
    
    result = await cache.get("prompt", "model", 0.1)
    assert result is not None
    assert result.content == "Cached content"

@pytest.mark.asyncio
async def test_llm_client_uses_cache():
    # Create a concrete implementation of abstract LLMClient for testing
    class TestClient(LLMClient):
        async def _generate_raw(self, prompt, system_prompt=None, temperature=None, max_tokens=None):
            return LLMResponse(
                content="Fresh content",
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
                model="test-model"
            )
        
        async def generate_structured(self, *args, **kwargs):
            pass

    client = TestClient()
    client.model = "test-model"
    client.temperature = 0.5

    # Mock the global llm_cache instance
    with patch('app.services.llm_client.llm_cache') as mock_cache:
        # Scenario 1: Cache Miss
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        response = await client.generate("test prompt")

        assert response.content == "Fresh content"
        mock_cache.get.assert_called_once()
        mock_cache.set.assert_called_once()

        # Scenario 2: Cache Hit
        mock_cache.get.reset_mock()
        mock_cache.set.reset_mock()
        mock_cache.get = AsyncMock(return_value=LLMResponse(
            content="Cached content",
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
            model="test-model"
        ))
        
        response = await client.generate("test prompt")
        
        assert response.content == "Cached content"
        mock_cache.get.assert_called_once()
        mock_cache.set.assert_not_called()
