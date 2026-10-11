#!/usr/bin/env bash
# 启动自建联网检索服务（Linux）：127.0.0.1:8888，SearXNG 协议兼容
set -u
cd "$(dirname "$0")/fastapi-app"

if [ ! -x .venv/bin/python ]; then
    echo "[错误] 未找到 .venv，请先完成后端环境安装"
    exit 1
fi

echo "[检索] 启动自建联网检索服务 (127.0.0.1:8888) ..."
exec .venv/bin/python -m uvicorn search_service.main:app --host 127.0.0.1 --port "${PORT:-8888}"
