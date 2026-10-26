# Production Multi-Stage Dockerfile for Telegram to Dropbox Sync & Webhook Dispatcher
FROM python:3.11-slim

# Prevent Python from writing bytecode and enable instant logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Working directory
WORKDIR /app

# Install native compilation dependencies for cryptg (MTProto cryptography) and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose Webhook server port
EXPOSE 8080

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default: Launch Webhook to GitHub Actions Dispatcher
CMD ["python", "webhook/server.py"]
