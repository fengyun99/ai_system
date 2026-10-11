#!/usr/bin/env bash
# 启动前端 Vite（Linux）：http://127.0.0.1:5173（/api 与 /mcp 代理到 9310）
set -u
cd "$(dirname "$0")/web"

command -v npm >/dev/null 2>&1 || { echo "[错误] 未安装 Node.js/npm"; exit 1; }

if [ ! -d node_modules ]; then
    echo "[提示] 首次运行，安装依赖..."
    npm install || exit 1
fi

echo "[前端] 启动 Vite (http://127.0.0.1:5173) ..."
exec npm run dev
