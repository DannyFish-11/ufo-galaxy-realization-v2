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

# Copy project files (precise COPY, no whole project)
COPY --chown=galaxy:galaxy requirements.txt main.py ./
COPY --chown=galaxy:galaxy core/ ./core/
COPY --chown=galaxy:galaxy galaxy_gateway/ ./galaxy_gateway/
COPY --chown=galaxy:galaxy contracts/ ./contracts/
COPY --chown=galaxy:galaxy config/ ./config/
COPY --chown=galaxy:galaxy cli/ ./cli/
COPY --chown=galaxy:galaxy nodes/ ./nodes/
COPY --chown=galaxy:galaxy enhancements/ ./enhancements/
COPY --chown=galaxy:galaxy audit/ ./audit/

# 构建期把应用代码编译成 .pyc。
#
# 为什么需要:上面(以及另外三个 Dockerfile)都设了 PYTHONDONTWRITEBYTECODE=1 ——
# 那是容器里的常见做法(镜像干净、不留运行期写入),但它同时意味着**运行期永远
# 不会生成 .pyc**。而构建时又没有任何预编译,于是应用代码在**每一次进程启动**
# 都要重新编译一遍,不是只有第一次。
#
# 实测(隔离掉磁盘冷读与 site-packages 的影响,各跑 3 次取稳定值):
#     应用代码无 .pyc + DONTWRITEBYTECODE   2315 / 2322 / 2384 ms
#     构建期 compileall 之后               1919 / 1930 / 2036 ms
# 约省 380 ms 每次启动(~16%)。不大,但它是纯收益:代码不变、行为不变,
# 只是把一份每次都要重做的工作挪到构建期做一次。
#
# compileall 显式调用 py_compile,不受 PYTHONDONTWRITEBYTECODE 影响,
# 所以运行期那个环境变量可以照旧保留。
# -q 只报错误;失败不阻断构建(个别文件语法不兼容当前版本时,退化成运行期编译)。
RUN python -m compileall -q core/ galaxy_gateway/ nodes/ enhancements/ contracts/ || true

USER galaxy

# Main API + Web UI (灵动岛 Dashboard) — single client entry port
EXPOSE 9000

# Health check (uses core health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:9000/health/live || exit 1

# Use tini as init to handle signals properly
ENTRYPOINT ["tini", "--"]

# Default: launch via unified_launcher on port 9000 (single source-of-truth API entry)
CMD ["python", "main.py"]
