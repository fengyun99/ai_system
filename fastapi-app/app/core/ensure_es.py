# -*- coding: utf-8 -*-
"""ES 就绪保障——启动阶段探测并等待 ES 可达（不负责启动 ES）。

背景：ES 采用手动方式启动——直接双击 D:\\elasticsearch-8.19.22\\bin\\elasticsearch.bat，
或运行项目 start-es.bat（等价的幂等封装，已在运行则跳过）。不开机自启、
后端不再自动启动任何 ES 实例：曾通过 Windows 服务（net start）自动拉起，
但服务实例与手动 bat 实例会争抽数据目录锁（node.lock）导致后者启动失败，已弃用。
"""
from __future__ import annotations

import asyncio
import socket

WAIT_SECONDS = 180         # 冷启动实测约 2 分钟才监听 9200，90 秒会误报失败
PROBE_INTERVAL = 3


def es_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


async def ensure_es(host: str, port: int) -> bool:
    """等待 ES 可达；不可达时打印手动启动指引，返回最终是否可达。"""
    if es_reachable(host, port):
        return True
    print(f"[ensure_es] {host}:{port} 不可达（ES 不会自动启动）")
    print("[ensure_es] 请手动启动：双击 D:\\elasticsearch-8.19.22\\bin\\elasticsearch.bat，或运行项目 start-es.bat")
    for _ in range(WAIT_SECONDS // PROBE_INTERVAL):
        await asyncio.sleep(PROBE_INTERVAL)
        if es_reachable(host, port):
            print(f"[ensure_es] 服务已就绪: {host}:{port}")
            return True
    print(f"[ensure_es] 等待 {WAIT_SECONDS}s 后仍不可达")
    return False
