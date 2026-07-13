# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.7.19

FROM ${UV_IMAGE} AS uv-bin
FROM ${PYTHON_IMAGE} AS runtime

ARG FONTCONFIG_VERSION=2.14.1-4
ARG FONTS_LIBERATION_VERSION=2.1.5-1
ARG FONTS_NOTO_VERSION=20201225-1

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/mandate \
    PATH=/app/.venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/services/worker:/app/packages/shared-schemas/python \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv-bin /uv /uvx /bin/

WORKDIR /app

# WeasyPrint's documented Debian wheel dependencies and version-pinned fonts.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        fontconfig=${FONTCONFIG_VERSION} \
        fonts-liberation2=${FONTS_LIBERATION_VERSION} \
        fonts-noto-core=${FONTS_NOTO_VERSION} \
        libharfbuzz-subset0 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && playwright install --with-deps chromium \
    && fc-cache --force \
    && fc-match "Noto Sans" | grep --quiet "Noto Sans" \
    && fc-match "Liberation Serif" | grep --quiet "Liberation Serif" \
    && python -c "from weasyprint import HTML; HTML(string='<p>Mandate</p>').write_pdf('/tmp/render-probe.pdf')" \
    && test -s /tmp/render-probe.pdf \
    && rm -f /tmp/render-probe.pdf \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /ms-playwright

RUN groupadd --gid 10001 mandate \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin mandate \
    && install -d --owner=10001 --group=10001 /home/mandate/.cache

COPY --chown=10001:10001 services/worker ./services/worker
COPY --chown=10001:10001 packages/shared-schemas/python ./packages/shared-schemas/python

USER 10001:10001
STOPSIGNAL SIGTERM

FROM runtime AS worker
LABEL org.opencontainers.image.title="Mandate worker"
EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2).read()"]
CMD ["uvicorn", "mandate_worker.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1", "--no-access-log"]

FROM runtime AS renderer
LABEL org.opencontainers.image.title="Mandate renderer"
EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=2).read()"]
CMD ["uvicorn", "mandate_worker.render.main:app", "--host", "127.0.0.1", "--port", "8082", "--workers", "1", "--no-access-log"]
