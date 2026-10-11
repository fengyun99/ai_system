#!/usr/bin/env bash
# 一键停止（Linux）：后端/检索/前端（按 pidfile，退化按端口）+ ES 服务
set -u
cd "$(dirname "$0")"
ES_UNIT="${ES_UNIT:-elasticsearch}"

kill_by_port() {  # $1=端口
    local pids=""
    if command -v fuser >/dev/null 2>&1; then
        pids=$(fuser "$1/tcp" 2>/dev/null)
    elif command -v lsof >/dev/null 2>&1; then
        pids=$(lsof -t -i :"$1" 2>/dev/null)
    elif command -v ss >/dev/null 2>&1; then
        pids=$(ss -ltnp "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u)
    fi
    [ -n "$pids" ] && kill $pids 2>/dev/null && echo "[停止] 端口 $1 进程 $pids"
    return 0
}

for name in backend search frontend; do
    if [ -f "run/$name.pid" ]; then
        pid=$(cat "run/$name.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null && echo "[停止] $name (PID $pid)"
        else
            echo "[停止] $name (PID $pid) 已不在运行"
        fi
        rm -f "run/$name.pid"
    fi
done

sleep 2
# 兜底：pidfile 丢失时按端口清理
for port in 9310 8888 5173; do kill_by_port "$port"; done

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$ES_UNIT" 2>/dev/null; then
    sudo systemctl stop "$ES_UNIT" 2>/dev/null || systemctl stop "$ES_UNIT" 2>/dev/null \
        && echo "[停止] ES 服务" || echo "[停止] ES: 无权限（尝试 sudo）"
else
    echo "[停止] ES 服务未在运行"
fi

echo "[停止] 完成（MySQL/Redis 未动）"
