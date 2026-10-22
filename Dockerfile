# Production Dockerfile for Northflank & Cloud Deployments
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Set application directory
WORKDIR /app

# Install build dependencies for fast native cryptography extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy repository source code
COPY . .

# Expose HTTP health check port
EXPOSE 8000

# Run sync engine
CMD ["python", "bot.py"]
