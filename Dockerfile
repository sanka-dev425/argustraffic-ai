# ArgusTraffic AI - Production Dockerfile
FROM python:3.11-slim

# Install system dependencies for OpenCV and multimedia processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications
COPY requirements.txt setup.py ./

# Install python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code and configurations
COPY src/ ./src/
COPY configs/ ./configs/
COPY scripts/ ./scripts/
COPY detect.py README.md ./

# Create persistent data and snapshot directories
RUN mkdir -p /app/data /app/snapshots

# Install local package in editable mode
RUN pip install --no-cache-dir -e .

# Security: Create non-root user (CIS Container Security Standard)
RUN useradd -m -u 10001 -s /bin/bash argususer && \
    chown -R argususer:argususer /app

USER argususer

# Expose API and WebSocket port
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Launch ASGI application server
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
