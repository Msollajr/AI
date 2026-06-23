# =============================================================================
# IS 365 - Practical Assignment: Self-Hosted LLM Application
# Option C: Dockerfile — Containerize the FastAPI Backend
#
# Build:   docker build -t udsm-llm-backend .
# Run:     docker run -p 8000:8000 udsm-llm-backend
# =============================================================================

FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code (only what's needed at runtime)
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY knowledge-base/ ./knowledge-base/

# Create logs directory
RUN mkdir -p backend/logs

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with python -m to use the correct environment
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
