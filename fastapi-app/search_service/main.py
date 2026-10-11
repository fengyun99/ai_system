# -*- coding: utf-8 -*-
"""自建联网检索服务——SearXNG 协议兼容的轻量替代实现（开源组件，本机自托管）。

设计要点：
  1. 对外暴露与 SearXNG 一致的 JSON API：GET /search?q=..&format=json
     （响应 shape 对齐 SearXNG：{query, number_of_results, results:[{title,url,content,engine,score}]}），
     因此主服务客户端代码与"换成真 SearXNG（docker run searxng/searxng）"完全同构，只改 base_url；
  2. 引擎侧为多引擎聚合（Bing + 搜狗；可选 DuckDuckGo），并发抓取 + URL 去重 + 轮转合并，
     不使用任何模型厂商的联网能力（回答材料由本服务提供，再交给 LLM 总结）；
  3. 零重型依赖：httpx + lxml。

启动：uvicorn search_service.main:app --host 127.0.0.1 --port 8888
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import quote, urljoin

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from lxml import html as lh

APP_VERSION = "1.0.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

app = FastAPI(title="自建联网检索服务（SearXNG 协议兼容）", version=APP_VERSION)


# ------------------------------------------------------------------ 引擎

async def _engine_bing(client: httpx.AsyncClient, q: str, limit: int) -> list[dict]:
    resp = await client.get("https://cn.bing.com/search",
                            params={"q": q, "setlang": "zh-CN", "ensearch": "0"},
                            headers={"User-Agent": UA}, timeout=8)
    doc = lh.fromstring(resp.text)
    out = []
    for item in doc.cssselect("li.b_algo")[:limit]:
        a = item.cssselect("h2 a")
        if not a:
            continue
        snip = item.cssselect(".b_caption p, .b_algoSlug, .b_lineclamp2, .b_snippet")
        out.append({
            "title": a[0].text_content().strip(),
            "url": a[0].get("href") or "",
            "content": snip[0].text_content().strip() if snip else "",
            "engine": "bing",
        })
    return out


async def _engine_sogou(client: httpx.AsyncClient, q: str, limit: int) -> list[dict]:
    resp = await client.get("https://www.sogou.com/web",
                            params={"query": q}, headers={"User-Agent": UA}, timeout=8)
    doc = lh.fromstring(resp.text)
    out = []
    for item in doc.cssselect("div.vrwrap")[:limit]:
        a = item.cssselect("h3 a")
        if not a or not a[0].get("href"):
            continue
        snip = item.cssselect("p.str_info, .space-txt, .fz-mid, .text-layout")
        href = a[0].get("href") or ""
        if href.startswith("/"):
            href = urljoin("https://www.sogou.com", href)
        out.append({
            "title": a[0].text_content().strip(),
            "url": href,
            "content": snip[0].text_content().strip() if snip else "",
            "engine": "sogou",
        })
    return out


async def _engine_duckduckgo(client: httpx.AsyncClient, q: str, limit: int) -> list[dict]:
    resp = await client.get("https://html.duckduckgo.com/html/",
                            params={"q": q}, headers={"User-Agent": UA}, timeout=8)
    doc = lh.fromstring(resp.text)
    out = []
    for item in doc.cssselect("div.result")[:limit]:
        a = item.cssselect("a.result__a")
        snip = item.cssselect("a.result__snippet, .result__snippet")
        if not a:
            continue
        out.append({
            "title": a[0].text_content().strip(),
            "url": a[0].get("href") or "",
            "content": snip[0].text_content().strip() if snip else "",
            "engine": "duckduckgo",
        })
    return out


ENGINES = {
    "bing": _engine_bing,
    "sogou": _engine_sogou,
    "duckduckgo": _engine_duckduckgo,
}
DEFAULT_ENGINES = ["bing", "sogou"]


def _round_robin(groups: list[list[dict]], limit: int) -> list[dict]:
    """多引擎轮转合并 + URL 去重（保序、按引擎交错，避免单引擎独占）。"""
    seen: set[str] = set()
    out: list[dict] = []
    idx = 0
    while len(out) < limit and any(idx < len(g) for g in groups):
        for g in groups:
            if idx < len(g):
                item = g[idx]
                key = item["url"].split("#")[0]
                if key and key not in seen:
                    seen.add(key)
                    out.append(item)
                    if len(out) >= limit:
                        break
        idx += 1
    return out


# ------------------------------------------------------------------ API

@app.get("/health")
async def health():
    return {"status": "ok", "service": "local-search", "engines": list(ENGINES)}


@app.get("/search")
async def search(
    q: str = Query(..., description="检索词"),
    format: str = Query("json"),                      # noqa: A002 对齐 SearXNG 协议
    engines: str = Query("", description="逗号分隔，缺省 bing,sogou"),
    limit: int = Query(8, ge=1, le=20),
    language: str = Query("zh-CN"),
):
    """SearXNG 兼容检索入口（format=json）。"""
    if format != "json":
        return JSONResponse({"error": "only format=json is supported"}, status_code=400)

    names = [n.strip() for n in engines.split(",") if n.strip()] or DEFAULT_ENGINES
    names = [n for n in names if n in ENGINES]
    if not names:
        return JSONResponse({"error": f"no valid engines, available={list(ENGINES)}"},
                            status_code=400)

    t0 = time.perf_counter()
    per_engine = max(4, limit)          # 每引擎多取一些供去重后截断
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(
            *[ENGINES[n](client, q, per_engine) for n in names],
            return_exceptions=True,
        )
    groups: list[list[dict]] = []
    errors: dict[str, str] = {}
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            errors[name] = f"{type(res).__name__}: {str(res)[:120]}"
            groups.append([])
        else:
            groups.append(res)

    merged = _round_robin(groups, limit)
    for i, item in enumerate(merged):
        item["score"] = round(1.0 - i * 0.05, 3)      # 位次分（SearXNG 亦为启发式分）
        item["content"] = " ".join(item["content"].split())[:500]

    return {
        "query": q,
        "number_of_results": len(merged),
        "results": merged,
        "engines_used": names,
        "engine_errors": errors,
        "took_ms": int((time.perf_counter() - t0) * 1000),
        "source": "local-search-service",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("search_service.main:app", host="127.0.0.1", port=8888)
