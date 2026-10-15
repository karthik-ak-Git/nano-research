# Multi-stage Dockerfile for Norwegian Company Intelligence Agent
FROM python:3.11-slim as base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN pip install --no-cache-dir uv

# Copy dependency specifications
COPY pyproject.toml .

# Install dependencies
RUN uv pip install -e .

# Copy application source code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY data/ ./data/
COPY profiles/ ./profiles/
COPY reports/ ./reports/

# Default port for optional FastAPI interface
EXPOSE 8000

# Default entrypoint runs the CLI
ENTRYPOINT ["company-agent"]
CMD ["--help"]
