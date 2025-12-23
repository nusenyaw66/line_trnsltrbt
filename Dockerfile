FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# System deps for building wheels (line-bot-sdk, google-cloud-translate)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies via Poetry (no virtualenv to keep image small)
COPY pyproject.toml poetry.lock* /app/
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --no-root

# Copy application code
COPY . /app

# Cloud Run will set $PORT; default to 8080 for local use
CMD ["gunicorn", "-b", "0.0.0.0:8080", "line_translator_bot:app"]

