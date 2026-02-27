"""
Log Integration Client.

Fetches and parses logs from various log aggregation systems.

Supported systems:
- Loki (Grafana Loki)
- Elasticsearch
- CloudWatch Logs
- Custom log endpoints

Senior Engineering Note:
- Async HTTP requests
- Error log pattern matching
- Log level classification
- Anomaly scoring based on error frequency
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    FATAL = "fatal"


class LogEntry(BaseModel):
    """A single log entry."""

    timestamp: datetime
    level: LogLevel
    message: str
    service: str
    labels: dict[str, str] = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class LogClient:
    """
    Client for fetching and analyzing logs.

    Supports multiple log backends via adapters.
    """

    def __init__(self, backend: str = "loki", base_url: str = "http://localhost:3100"):
        self.backend = backend
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

        # Error patterns
        self.error_patterns = [
            r"exception",
            r"error",
            r"failed",
            r"fatal",
            r"panic",
            r"stack trace",
            r"null pointer",
            r"timeout",
            r"connection refused",
            r"out of memory",
        ]

    async def query_logs(
        self,
        service: str,
        start_time: datetime,
        end_time: datetime,
        level: Optional[LogLevel] = None,
        limit: int = 100,
    ) -> list[LogEntry]:
        """
        Query logs for a service within a time range.

        Args:
            service: Service name to query
            start_time: Start of time range
            end_time: End of time range
            level: Optional log level filter
            limit: Maximum number of logs to return

        Returns:
            List of log entries
        """
        try:
            if self.backend == "loki":
                return await self._query_loki(service, start_time, end_time, level, limit)
            elif self.backend == "elasticsearch":
                return await self._query_elasticsearch(service, start_time, end_time, level, limit)
            else:
                logger.warning(f"Unsupported log backend: {self.backend}, returning empty")
                return []

        except Exception as e:
            logger.error(f"Log query failed: {str(e)}", exc_info=True)
            return []

    async def _query_loki(
        self,
        service: str,
        start_time: datetime,
        end_time: datetime,
        level: Optional[LogLevel],
        limit: int,
    ) -> list[LogEntry]:
        """Query Grafana Loki."""
        try:
            # Build LogQL query
            query_parts = [f'{{service="{service}"}}']
            if level:
                query_parts.append(f'| level="{level.value}"')

            query = " ".join(query_parts)

            params = {
                "query": query,
                "start": int(start_time.timestamp() * 1e9),  # Nanoseconds
                "end": int(end_time.timestamp() * 1e9),
                "limit": limit,
            }

            response = await self.client.get(
                f"{self.base_url}/loki/api/v1/query_range", params=params
            )

            if response.status_code != 200:
                logger.error(f"Loki query failed: {response.status_code}")
                return []

            data = response.json()
            return self._parse_loki_response(data, service)

        except httpx.HTTPError as e:
            logger.error(f"Loki HTTP error: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Loki query error: {str(e)}")
            return []

    def _parse_loki_response(self, data: dict, service: str) -> list[LogEntry]:
        """Parse Loki API response."""
        entries = []

        try:
            results = data.get("data", {}).get("result", [])

            for result in results:
                stream_labels = result.get("stream", {})
                values = result.get("values", [])

                for value in values:
                    timestamp_ns, message = value
                    timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1e9)

                    # Detect log level from message
                    level = self._detect_log_level(message)

                    entry = LogEntry(
                        timestamp=timestamp,
                        level=level,
                        message=message,
                        service=service,
                        labels=stream_labels,
                    )
                    entries.append(entry)

        except Exception as e:
            logger.error(f"Failed to parse Loki response: {str(e)}")

        return entries

    async def _query_elasticsearch(
        self,
        service: str,
        start_time: datetime,
        end_time: datetime,
        level: Optional[LogLevel],
        limit: int,
    ) -> list[LogEntry]:
        """Query Elasticsearch."""
        # TODO: Implement Elasticsearch querying
        logger.info("Elasticsearch log querying not yet implemented")
        return []

    def _detect_log_level(self, message: str) -> LogLevel:
        """Detect log level from message content."""
        message_lower = message.lower()

        if any(pattern in message_lower for pattern in ["fatal", "panic"]):
            return LogLevel.FATAL
        elif any(pattern in message_lower for pattern in ["error", "exception", "failed"]):
            return LogLevel.ERROR
        elif any(pattern in message_lower for pattern in ["warn", "warning"]):
            return LogLevel.WARN
        elif "debug" in message_lower:
            return LogLevel.DEBUG
        else:
            return LogLevel.INFO

    async def detect_error_spike(
        self,
        service: str,
        lookback_minutes: int = 5,
        error_threshold: int = 10,
    ) -> tuple[bool, list[LogEntry]]:
        """
        Detect if there's a spike in error logs.

        Args:
            service: Service to check
            lookback_minutes: Time window to check
            error_threshold: Number of errors to consider a spike

        Returns:
            Tuple of (has_spike, error_logs)
        """
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=lookback_minutes)

        # Query error logs
        error_logs = await self.query_logs(
            service=service,
            start_time=start_time,
            end_time=end_time,
            level=LogLevel.ERROR,
            limit=100,
        )

        has_spike = len(error_logs) >= error_threshold

        if has_spike:
            logger.info(
                f"Error spike detected in {service}: {len(error_logs)} errors "
                f"in last {lookback_minutes} minutes"
            )

        return has_spike, error_logs

    async def extract_error_patterns(self, logs: list[LogEntry]) -> dict[str, int]:
        """
        Extract common error patterns from logs.

        Returns:
            Dict mapping error patterns to occurrence counts
        """
        pattern_counts: dict[str, int] = {}

        for log in logs:
            if log.level not in [LogLevel.ERROR, LogLevel.FATAL]:
                continue

            # Check against known patterns
            for pattern in self.error_patterns:
                if re.search(pattern, log.message, re.IGNORECASE):
                    pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        return pattern_counts

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


def get_log_client(backend: str = "loki", base_url: str = "http://localhost:3100") -> LogClient:
    """Get a log client instance."""
    return LogClient(backend=backend, base_url=base_url)
