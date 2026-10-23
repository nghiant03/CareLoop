FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
ARG OCR_BACKEND=gpu
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --extra ocr --extra "ocr-${OCR_BACKEND}"

FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV HOME=/var/lib/careloop
ENV LD_LIBRARY_PATH="/app/.venv/lib/python3.12/site-packages/nvidia/cuda_runtime/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cusolver/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cusparse/lib:/app/.venv/lib/python3.12/site-packages/nvidia/cufft/lib:/app/.venv/lib/python3.12/site-packages/nvidia/curand/lib:/app/.venv/lib/python3.12/site-packages/nvidia/nccl/lib:/app/.venv/lib/python3.12/site-packages/nvidia/nvjitlink/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64"
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
RUN mkdir -p /var/lib/careloop && chown 10001:10001 /var/lib/careloop
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "careloop.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
