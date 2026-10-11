# -*- coding: utf-8 -*-
"""票据 01：计量网关补洞——embeddings 真值口径 + rerank 失败路径记账。

验收（.scratch/observability/issues/01）：
  - embeddings：供应商返回 usage 时记真值（estimated=0），缺失才字符估算（estimated=1）
  - rerank 传输失败 / HTTP 非 200 / 响应缺 results：抛 RerankError 前完成估算记账
  - 既有成功路径口径（真值优先、估算兜底）锁定防回归
"""
from __future__ import annotations

import httpx
import pytest

from app.rag import llm
from app.rag.llm import ModelEntry, RerankError, TokenMeter, embed_texts, rerank_documents


# ---------------------------------------------------------------- fakes

def _entry(key: str, model: str) -> ModelEntry:
    return ModelEntry(key=key, base_url="http://llm.test/v1", api_keys=["sk-test"], model=model)


class _Usage:
    def __init__(self, prompt_tokens):
        self.prompt_tokens = prompt_tokens


class _EmbedResp:
    def __init__(self, n: int, usage):
        self.data = [type("D", (), {"embedding": [0.1, 0.2]})() for _ in range(n)]
        self.usage = usage


class _FakeEmbedClient:
    def __init__(self, resp):
        class _Embeddings:
            async def create(self, *, model, input):
                return resp
        self.embeddings = _Embeddings()


def _patch_embed(monkeypatch, key: str, resp) -> None:
    monkeypatch.setitem(llm._ENTRIES, key, _entry(key, "emb-model"))
    monkeypatch.setitem(llm._EMBED_CLIENTS, key, _FakeEmbedClient(resp))


def _patch_rerank(monkeypatch, *, response=None, exc=None) -> None:
    monkeypatch.setattr(llm, "get_settings", lambda: {"rag": {"rerank_key": "rerank"}})
    monkeypatch.setitem(llm._ENTRIES, "rerank", _entry("rerank", "rr-model"))

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kw):
            if exc:
                raise exc
            return response

    monkeypatch.setattr(llm.httpx, "AsyncClient", Client)


def _http_resp(status_code: int, body: dict, text: str = ""):
    return type("R", (), {"status_code": status_code,
                          "json": lambda self: body, "text": text})()


# ---------------------------------------------------------------- embeddings

async def test_embed_usage_true_value(monkeypatch):
    _patch_embed(monkeypatch, "embed-test", _EmbedResp(2, _Usage(prompt_tokens=123)))
    m = TokenMeter()
    vecs = await embed_texts(["你好世界", "hello"], "embed-test", meter=m)
    assert len(vecs) == 2
    row = m.rows[0]
    assert row.prompt_tokens == 123
    assert row.estimated == 0


async def test_embed_missing_usage_falls_back_to_estimate(monkeypatch):
    texts = ["你好世界", "hello"]
    _patch_embed(monkeypatch, "embed-test", _EmbedResp(2, None))
    m = TokenMeter()
    await embed_texts(texts, "embed-test", meter=m)
    row = m.rows[0]
    assert row.prompt_tokens == sum(len(t) for t in texts)
    assert row.estimated == 1


async def test_embed_zero_usage_counts_as_missing(monkeypatch):
    _patch_embed(monkeypatch, "embed-test", _EmbedResp(1, _Usage(prompt_tokens=0)))
    m = TokenMeter()
    await embed_texts(["四个字"], "embed-test", meter=m)
    row = m.rows[0]
    assert row.prompt_tokens == 3
    assert row.estimated == 1


# ---------------------------------------------------------------- rerank 成功路径（锁定既有行为）

async def test_rerank_success_usage_true_value(monkeypatch):
    body = {"results": [{"index": 0, "relevance_score": 0.9}],
            "usage": {"prompt_tokens": 77, "total_tokens": 90}}
    _patch_rerank(monkeypatch, response=_http_resp(200, body))
    m = TokenMeter()
    out = await rerank_documents("查询", ["文档一", "文档二"], top_n=1, meter=m)
    assert out == [(0, 0.9)]
    row = m.rows[0]
    assert row.prompt_tokens == 77
    assert row.estimated == 0


async def test_rerank_success_missing_usage_estimates(monkeypatch):
    body = {"results": [{"index": 1, "relevance_score": 0.5}]}
    _patch_rerank(monkeypatch, response=_http_resp(200, body))
    m = TokenMeter()
    await rerank_documents("查询", ["文档一"], top_n=1, meter=m)
    row = m.rows[0]
    assert row.prompt_tokens == len("查询") + len("文档一")
    assert row.estimated == 1


# ---------------------------------------------------------------- rerank 失败路径（票据要求）

async def test_rerank_transport_failure_meters_before_raise(monkeypatch):
    _patch_rerank(monkeypatch, exc=httpx.ConnectError("boom"))
    m = TokenMeter()
    with pytest.raises(RerankError):
        await rerank_documents("查询", ["文档一", "文档二"], top_n=2, meter=m)
    row = m.rows[0]
    assert row.prompt_tokens == len("查询") + len("文档一") + len("文档二")
    assert row.estimated == 1


async def test_rerank_http_error_meters_before_raise(monkeypatch):
    _patch_rerank(monkeypatch, response=_http_resp(500, {}, text="server error"))
    m = TokenMeter()
    with pytest.raises(RerankError):
        await rerank_documents("查询", ["文档"], top_n=1, meter=m)
    row = m.rows[0]
    assert row.prompt_tokens == len("查询") + len("文档")
    assert row.estimated == 1


async def test_rerank_missing_results_meters_before_raise(monkeypatch):
    _patch_rerank(monkeypatch, response=_http_resp(200, {}))
    m = TokenMeter()
    with pytest.raises(RerankError):
        await rerank_documents("查询", ["文档"], top_n=1, meter=m)
    row = m.rows[0]
    assert row.prompt_tokens == len("查询") + len("文档")
    assert row.estimated == 1
