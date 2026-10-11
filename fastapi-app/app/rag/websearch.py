# -*- coding: utf-8 -*-
"""联网检索客户端——对接自建检索服务（SearXNG 协议兼容）。

约定：材料来自**自建检索服务**（本仓库 search_service，或 docker 部署的真 SearXNG），
不调用任何模型厂商的联网能力；LLM 只负责对检索材料做归纳生成。
服务不可用时抛 WebSearchError，由链路按"联网不可用→拒答"降级（不阻塞其它路径）。
"""
from __future__ import annotations

import httpx

from app.settings import get_settings


class WebSearchError(Exception):
    """联网检索失败（服务不可达/非 200/响应畸形/未启用）。"""


def _cfg() -> dict:
    return get_settings().get("websearch") or {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", False))


async def search(query: str, limit: int | None = None) -> list[dict]:
    """执行联网检索，返回 [{title, url, content, engine, score}]。

    protocol: GET {base_url}/search?q=..&format=json（SearXNG 同构）。
    """
    cfg = _cfg()
    if not cfg.get("enabled"):
        raise WebSearchError("联网检索未启用（websearch.enabled=false）")
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise WebSearchError("未配置 websearch.base_url")

    params = {
        "q": query,
        "format": "json",
        "limit": int(limit or cfg.get("limit", 6)),
    }
    if cfg.get("engines"):
        params["engines"] = cfg["engines"]
    timeout = int(cfg.get("timeout_ms", 15000)) / 1000
    last_err: Exception | None = None
    resp = None
    for _attempt in range(2):        # 检索幂等：瞬时失败重试一次（引擎限流/抖动）
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base}/search", params=params)
            if resp.status_code == 200:
                break
            last_err = WebSearchError(f"检索服务 HTTP {resp.status_code}: {resp.text[:150]}")
        except httpx.HTTPError as exc:
            last_err = WebSearchError(f"检索服务不可达: {exc}")
    if resp is None or resp.status_code != 200:
        raise last_err or WebSearchError("检索失败")
    try:
        body = resp.json()
    except ValueError as exc:
        raise WebSearchError(f"检索服务响应非 JSON（是否关闭了 JSON 格式?）: {exc}") from exc
    results = body.get("results")
    if results is None:
        raise WebSearchError(f"检索响应缺 results: {str(body)[:150]}")
    return [{
        "title": (r.get("title") or "").strip(),
        "url": r.get("url") or "",
        "content": (r.get("content") or "").strip(),
        "engine": r.get("engine") or "",
        "score": r.get("score"),
    } for r in results if r.get("url") or r.get("content")]
