#!/usr/bin/env bash
# 一键启动（Linux）：ES → 后端 9310 → 检索 8888 → 前端 5173
# 后台方式运行，日志在 logs/，PID 记录在 run/（供 stop-all.sh 使用）
set -u
cd "$(dirname "$0")"
mkdir -p logs run

echo "[ALL] 1/4 Elasticsearch ..."
bash start-es.sh || echo "[ALL] 警告: ES 未就绪，后端启动链会再尝试拉起"

start_one() {  # $1=名称 $2=脚本
    if [ -f "run/$1.pid" ] && kill -0 "$(cat run/$1.pid)" 2>/dev/null; then
        echo "[ALL] $1 已在运行 (PID $(cat run/$1.pid))"
        return
    fi
    nohup bash "$2" > "logs/$1.log" 2>&1 &
    echo $! > "run/$1.pid"
    echo "[ALL] $2 已启动 (PID $!, 日志 logs/$1.log)"
}

echo "[ALL] 2/4 后端 / 3/4 检索服务 / 4/4 前端 ..."
start_one backend  start-backend.sh
start_one search   start-search.sh
start_one frontend start-frontend.sh

echo "[ALL] 全部启动命令已发出（后端就绪约需 10-20 秒）"
echo "[ALL] 查看日志: tail -f logs/backend.log | 停止: bash stop-all.sh"
