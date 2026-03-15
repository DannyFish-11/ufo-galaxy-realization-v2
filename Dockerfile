# ============================================================
# Galaxy L4 — Production Docker Image
# Multi-stage build for smaller, secure images
# ============================================================

# ── Stage 1: Builder ──
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build-time system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──
FROM python:3.11-slim

LABEL maintainer="Galaxy Team"
LABEL version="2.3.23"

WORKDIR /app

# Runtime-only system deps (no compiler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libpq5 \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    GALAXY_HOME=/app \
    GALAXY_MODE=production

# Create non-root user before COPY
RUN groupadd -r galaxy && useradd -r -g galaxy -m -u 1000 galaxy \
    && mkdir -p /app/data /app/logs /app/config \
    && chown -R galaxy:galaxy /app

# Copy project files
COPY --chown=galaxy:galaxy . .

USER galaxy

# Main API + Web UI (灵动岛 Dashboard) — single client entry port
EXPOSE 9000

# Health check (uses core health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:9000/health/live || exit 1

# Use tini as init to handle signals properly
ENTRYPOINT ["tini", "--"]

# Default: launch via unified_launcher on port 9000 (single source-of-truth API entry)
CMD ["python", "unified_launcher.py", "--host", "0.0.0.0", "--port", "9000"]
