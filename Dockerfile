# =============================================================================
# UDSM Student Support AI — Production Dockerfile
#
# Build:   docker build -t udsm-llm-backend .
# Run:     docker run -p 8000:8000 udsm-llm-backend
# Compose: docker compose up -d
# =============================================================================

# ── Stage 1: dependency installer ─────────────────────────────────────────────
# Use a full builder stage so heavy compile tools don't bloat the final image.
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps needed to compile native extensions (e.g. tokenizers, hnswlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy production-only requirements (no streamlit / pytest)
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements-prod.txt

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Create a non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Runtime-only system library required by sentence-transformers (OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder (keeps final image lean)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY backend/       ./backend/
COPY frontend/      ./frontend/
COPY knowledge-base/ ./knowledge-base/
COPY alembic/       ./alembic/
COPY alembic.ini    ./

# Ensure runtime-writable directories exist and are owned by appuser
RUN mkdir -p backend/logs backend/vector_store .cache/huggingface && \
    chown -R appuser:appgroup /app

# Drop to non-root user
USER appuser

# ── Environment ───────────────────────────────────────────────────────────────
# Lets `from config import ...` resolve inside backend/
# Python 3.11 — full pre-built wheel support for chromadb, scikit-learn, sentence-transformers
ENV PYTHONPATH=/app/backend
# Tell sentence-transformers / HuggingFace to use a predictable cache directory
# (mount this as a volume so the model is only downloaded once)
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
# Prevent Python from buffering stdout/stderr (important for Docker log streaming)
ENV PYTHONUNBUFFERED=1

# Expose API port
EXPOSE 8000

# Health check — waits up to 2 min on first start (model download + index build)
HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run migrations and then start uvicorn directly from the backend directory
# PYTHONPATH=/app/backend ensures all relative imports (config, llm_client, etc.) resolve
CMD ["/bin/bash", "-c", "alembic upgrade head && python -m uvicorn main:app --host 0.0.0.0 --port 8000"]
