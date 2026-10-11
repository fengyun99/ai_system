#!/usr/bin/env bash
# 启动 Elasticsearch 并等待 9200 就绪（Linux）
# 优先走 systemd 服务；无 systemd 时给出手动启动提示。需要 root/sudo。
set -u
ES_HOST="${ES_HOST:-127.0.0.1}"
ES_PORT="${ES_PORT:-9200}"
ES_UNIT="${ES_UNIT:-elasticsearch}"   # systemd 单元名（tar 包安装默认 elasticsearch.service）

port_ready() { timeout 2 bash -c "</dev/tcp/$ES_HOST/$ES_PORT" 2>/dev/null; }

if port_ready; then
    echo "[ES] 端口 $ES_HOST:$ES_PORT 已就绪"
    exit 0
fi

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^$ES_UNIT"; then
    echo "[ES] 启动 systemd 服务 $ES_UNIT ..."
    if systemctl is-active --quiet "$ES_UNIT" 2>/dev/null; then
        echo "[ES] 服务已 active，等待端口..."
    else
        sudo systemctl start "$ES_UNIT" 2>/dev/null || systemctl start "$ES_UNIT" \
            || { echo "[ES] 错误: 无权限启动服务（尝试 sudo）"; exit 1; }
    fi
else
    echo "[ES] 未发现 systemd 单元 $ES_UNIT"
    echo "[ES] 请手动启动 ES，例如: <es-home>/bin/elasticsearch -d"
    exit 1
fi

echo "[ES] 等待端口就绪（最长 60s）..."
for _ in $(seq 1 30); do
    port_ready && { echo "[ES] 就绪: https://$ES_HOST:$ES_PORT"; exit 0; }
    sleep 2
done
echo "[ES] 警告: 60s 内未监听 $ES_PORT，请查看 ES 日志"
exit 1
