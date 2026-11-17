# Private Harbor example: replace the following value with this line if your
# organization mirrors the Astral image internally:
# ARG BASE_IMAGE=harbor.example.com/base/uv:python3.13-bookworm-slim
#
# The same can be supplied without editing this file:
# docker build --build-arg BASE_IMAGE=harbor.example.com/base/uv:python3.13-bookworm-slim -t qa-tool .
ARG BASE_IMAGE=ghcr.io/astral-sh/uv:python3.13-bookworm-slim
FROM ${BASE_IMAGE}

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Install locked runtime dependencies before copying the source, so this layer
# remains cached while application code changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

EXPOSE 8501

CMD ["qa-tool", "webapp", "--", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]

# Alternative without the Astral/uv base image. This is a complete Dockerfile
# using the official Python image and pip, but it resolves dependencies during
# each build rather than installing the exact versions in uv.lock.
#
# FROM python:3.13-slim
# WORKDIR /app
# COPY . .
# RUN pip install --no-cache-dir .
# EXPOSE 8501
# CMD ["qa-tool", "webapp", "--", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
