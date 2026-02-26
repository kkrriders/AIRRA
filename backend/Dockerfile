# Multi-stage build for production efficiency
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy prod dependency file only — dev tools (pytest, ruff, mypy) are in
# requirements-dev.txt and are never installed in the production image.
COPY requirements.txt ./

# Install production dependencies only
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint executable (before switching to non-root user)
RUN chmod +x entrypoint.sh

# Create non-root user
RUN useradd -m -u 1000 airra && chown -R airra:airra /app
USER airra

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start AIRRA backend API server (migrations handled by db-migrate service)
CMD ["./entrypoint.sh"]
