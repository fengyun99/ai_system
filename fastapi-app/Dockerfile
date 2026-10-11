# 后端镜像（backend / search / init 共用，差异在 command）
# 构建: docker build -t ai-system-backend -f Dockerfile .
FROM python:3.12-slim

# uv（官方单文件镜像拷贝二进制）
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

# 依赖层（锁文件未变则命中缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 应用代码
COPY app ./app
COPY search_service ./search_service
COPY scripts ./scripts
COPY config ./config

EXPOSE 9310 8888
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9310"]
