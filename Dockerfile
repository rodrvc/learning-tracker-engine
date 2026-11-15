# Production image: migrates, then serves the API and the web UI on $PORT.
# Configuration is environment only; see docs/deploy.md for the variables.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Reachable from outside the container. The port comes from $PORT
    # (injected by Railway) or LEARNING_TRACKER_WEB_PORT, else 8000.
    LEARNING_TRACKER_WEB_HOST=0.0.0.0

WORKDIR /app

COPY . .
RUN pip install ".[web]" \
    && useradd --create-home --uid 10001 app

USER app

EXPOSE 8000

# Validates settings (auth fails closed), applies pending migrations (a
# no-op when there are none), then serves. Any failure exits non-zero, so the
# platform keeps the previous deploy.
CMD ["python", "-m", "web.app", "--migrate"]
