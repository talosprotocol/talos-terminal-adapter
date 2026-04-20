# ========================================
# Builder Stage  
# ========================================
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libgmp-dev && \
    rm -rf /var/lib/apt/lists/*

COPY sdks/python /build/sdks/python
COPY contracts/python /build/contracts/python
COPY libs/talos-config /build/libs/talos-config
COPY services/terminal-adapter /build/services/terminal-adapter

RUN pip wheel --no-cache-dir --wheel-dir /wheels \
    rfc8785 \
    /build/sdks/python \
    /build/contracts/python \
    /build/libs/talos-config \
    /build/services/terminal-adapter

# ========================================
# Runtime Stage
# ========================================
FROM python:3.11-slim

ARG GIT_SHA=unknown
ARG VERSION=unknown
ARG BUILD_TIME=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/sdks/python/src \
    GIT_SHA=${GIT_SHA} \
    VERSION=${VERSION} \
    BUILD_TIME=${BUILD_TIME}

RUN groupadd --system --gid 1001 talos && \
    useradd --system --uid 1001 --gid talos --create-home talos

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# For terminal execution, we might need some basic tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends bash coreutils && \
    rm -rf /var/lib/apt/lists/*

# Written mounts for read-only root filesystem
RUN mkdir -p /tmp /var/run && chown -R 1001:1001 /tmp /var/run

USER 1001:1001

EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request, os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", 8085)}/health')" || exit 1

CMD ["sh", "-c", "uvicorn terminal_adapter.main:app --host 0.0.0.0 --port ${PORT:-8085}"]

LABEL org.opencontainers.image.source="https://github.com/talosprotocol/talos" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.licenses="Apache-2.0"
