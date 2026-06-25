# =============================================================================
# UDSM Student Support AI — Production Dockerfile
#
# Build:   docker build -t udsm-llm-backend .
# Run:     docker run -p 8000:8000 udsm-llm-backend
# Compose: docker-compose up -d
# =============================================================================

# ── Stage 1: dependency installer ─────────────────────────────────────────────
# Use a full builder stage so heavy compile tools don't bloat the final image.
FROM python:3.13-slim AS builder

WORKDIR /build

# System deps needed to compile native extensions (e.g. tokenizers, hnswlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Runtime-only system library required by sentence-transformers (OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder (keeps final image lean)
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY backend/   ./backend/
COPY frontend/  ./frontend/
COPY knowledge-base/ ./knowledge-base/

# Ensure logs and vector store directories exist
RUN mkdir -p backend/logs backend/vector_store

# ── Python path: lets `from config import ...` resolve inside backend/ ─────────
ENV PYTHONPATH=/app/backend
# Tell sentence-transformers / HuggingFace to use a predictable cache directory
# (mount this as a volume so the model is only downloaded once)
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

# Expose API port
EXPOSE 8000

# Health check — waits up to 2 min on first start (model download + index build)
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run uvicorn from the backend directory so relative imports resolve correctly
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
