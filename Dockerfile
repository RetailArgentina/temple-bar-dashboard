FROM python:3.12-slim

# Prevents .pyc files; forces stdout/stderr flush for Cloud Logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Non-root user — Cloud Run does not require root
RUN useradd --create-home --no-log-init appuser && \
    chown -R appuser:appuser /app
USER appuser

# PORT is injected by Cloud Run at runtime (default 8080)
# 1 worker: Cloud Run scales horizontally, not vertically
# 8 threads: handles concurrent requests within one instance
# --timeout 0: Cloud Run manages instance lifecycle
CMD exec gunicorn \
    --bind :$PORT \
    --workers 1 \
    --threads 8 \
    --timeout 0 \
    --access-logfile - \
    app:app
