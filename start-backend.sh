#!/usr/bin/env bash
# 启动后端 FastAPI（Linux）：127.0.0.1:9310，MCP 同进程挂载 /mcp
set -u
cd "$(dirname "$0")/fastapi-app"

if [ ! -x .venv/bin/python ]; then
    echo "[错误] 未找到 .venv，请先执行: uv sync"
    echo "  （无 uv 时: python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt）"
    exit 1
fi

# ES 未启动时自动拉起（需 sudo；失败不阻塞，交由后端启动链报错）
bash ../start-es.sh || true

echo "[后端] 启动 FastAPI (127.0.0.1:9310, MCP 挂载 /mcp) ..."
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-9310}"
