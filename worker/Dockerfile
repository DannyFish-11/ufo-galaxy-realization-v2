# ============================================================================
# Galaxy Agentic OS — Go Edge Worker
# Multi-stage build: compile → minimal runtime with Docker CLI
# ============================================================================

# ── Build stage ────────────────────────────────────────────────────────────
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /galaxy-worker ./cmd/worker/

# ── Runtime stage ──────────────────────────────────────────────────────────
FROM alpine:3.19

RUN apk add --no-cache \
    ca-certificates \
    docker-cli \
    python3 \
    nodejs

COPY --from=builder /galaxy-worker /usr/local/bin/galaxy-worker

# Health check (constraint C8)
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget --spider -q http://localhost:8300/health || exit 1

EXPOSE 8300

ENTRYPOINT ["galaxy-worker"]
