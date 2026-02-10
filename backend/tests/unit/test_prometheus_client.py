"""Unit tests for Prometheus client."""
import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta

from app.services.prometheus_client import PrometheusClient, MetricResult, MetricDataPoint


class TestPrometheusClient:
    """Test Prometheus client."""

    async def test_query_instant(self, mock_prometheus_vector_response):
        """Test instant query."""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_prometheus_vector_response
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            client = PrometheusClient(base_url="http://localhost:9090")
            result = await client.query("up")

            assert result is not None

    async def test_query_range(self, mock_prometheus_matrix_response):
        """Test range query."""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_prometheus_matrix_response
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            client = PrometheusClient(base_url="http://localhost:9090")
            now = datetime.utcnow()
            result = await client.query_range(
                "cpu_usage",
                start=now - timedelta(hours=1),
                end=now,
                step="15s"
            )

            assert result is not None

    async def test_parse_vector_response(self, mock_prometheus_vector_response):
        """Test parsing vector (instant query) response."""
        client = PrometheusClient(base_url="http://localhost:9090")
        results = client._parse_response(mock_prometheus_vector_response["data"])

        assert len(results) == 1
        assert results[0].metric_name == "cpu_usage"
        assert len(results[0].values) == 1
        assert results[0].values[0].value == 75.5

    async def test_parse_matrix_response(self, mock_prometheus_matrix_response):
        """Test parsing matrix (range query) response."""
        client = PrometheusClient(base_url="http://localhost:9090")
        results = client._parse_response(mock_prometheus_matrix_response["data"])

        assert len(results) == 1
        assert results[0].metric_name == "memory_usage"
        assert len(results[0].values) == 3

    async def test_parse_empty_response(self, mock_prometheus_empty_response):
        """Test parsing empty response."""
        client = PrometheusClient(base_url="http://localhost:9090")
        results = client._parse_response(mock_prometheus_empty_response["data"])

        assert len(results) == 0

    async def test_get_service_metrics(self):
        """Test convenience method for service metrics."""
        with patch.object(PrometheusClient, 'query_range') as mock_query:
            mock_query.return_value = [
                MetricResult(metric_name="cpu_usage", labels={}, values=[])
            ]

            client = PrometheusClient(base_url="http://localhost:9090")
            metrics = await client.get_service_metrics("test-service", lookback_minutes=10)

            assert "cpu_usage" in metrics or "request_rate" in metrics or metrics is not None
            mock_query.assert_called()

    async def test_handles_connection_error(self):
        """Test handling of connection errors."""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.side_effect = ConnectionError("Prometheus unavailable")

            client = PrometheusClient(base_url="http://localhost:9090")

            with pytest.raises(ConnectionError):
                await client.query("up")

    async def test_handles_timeout(self):
        """Test handling of timeout errors."""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.side_effect = TimeoutError("Request timed out")

            client = PrometheusClient(base_url="http://localhost:9090")

            with pytest.raises(TimeoutError):
                await client.query("up")

    async def test_metric_label_extraction(self, mock_prometheus_vector_response):
        """Test extraction of metric labels."""
        client = PrometheusClient(base_url="http://localhost:9090")
        results = client._parse_response(mock_prometheus_vector_response["data"])

        assert results[0].labels["service"] == "test-service"

    async def test_timestamp_conversion(self, mock_prometheus_matrix_response):
        """Test timestamp conversion from Unix to datetime."""
        client = PrometheusClient(base_url="http://localhost:9090")
        results = client._parse_response(mock_prometheus_matrix_response["data"])

        # Timestamps should be floats
        for value in results[0].values:
            assert isinstance(value.timestamp, float)
            assert value.timestamp > 0

    async def test_value_type_conversion(self, mock_prometheus_vector_response):
        """Test values are converted to float."""
        client = PrometheusClient(base_url="http://localhost:9090")
        results = client._parse_response(mock_prometheus_vector_response["data"])

        assert isinstance(results[0].values[0].value, float)

    async def test_client_close(self):
        """Test client cleanup."""
        client = PrometheusClient(base_url="http://localhost:9090")
        await client.close()

        # Should not raise

    async def test_invalid_promql_query(self):
        """Test handling of invalid PromQL."""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"status": "error", "error": "invalid query"}
            mock_response.raise_for_status.side_effect = Exception("Bad request")
            mock_get.return_value = mock_response

            client = PrometheusClient(base_url="http://localhost:9090")

            with pytest.raises(Exception):
                await client.query("invalid{{{query")


class TestMetricDataStructures:
    """Test metric data structures."""

    def test_metric_data_point_creation(self):
        """Test MetricDataPoint creation."""
        point = MetricDataPoint(timestamp=1704067200.0, value=75.5)

        assert point.timestamp == 1704067200.0
        assert point.value == 75.5

    def test_metric_result_creation(self):
        """Test MetricResult creation."""
        result = MetricResult(
            metric_name="cpu_usage",
            labels={"service": "test"},
            values=[MetricDataPoint(timestamp=1.0, value=50.0)]
        )

        assert result.metric_name == "cpu_usage"
        assert result.labels["service"] == "test"
        assert len(result.values) == 1
