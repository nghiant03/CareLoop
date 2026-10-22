FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "careloop.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
