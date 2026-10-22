FROM python:3.13-slim-bookworm AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY backend/ backend/
COPY shared/ shared/
COPY rules/ rules/
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/var/lib/careloop
RUN groupadd --gid 10001 careloop \
    && useradd --uid 10001 --gid careloop --no-create-home careloop \
    && mkdir -p /var/lib/careloop/artifacts /app \
    && chown -R careloop:careloop /var/lib/careloop
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -r /var/lib/apt/lists/*
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels careloop \
    && rm -r /wheels
WORKDIR /app
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app.deployment:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
