# -*- coding: utf-8 -*-
"""票据 02：行级记账贯通——token 记到具体阶段行。

验收（.scratch/observability/issues/02）：
  - 记账器按阶段行号记账、落库按行精确匹配（不再按类型聚合摊派）
  - 同类型多行各自归属本行消耗，逐行求和 == 轮次汇总
  - 每行携带真值/估算口径标记（任一组成计量为估算则该行标记 1）
"""
from __future__ import annotations

import httpx
import pytest

from app.rag import llm
from app.rag.graph import _stage
from app.rag.llm import ModelEntry, TokenMeter, embed_texts, rerank_documents


# ---------------------------------------------------------------- 记账器行级化

def test_meter_rows_carry_stage_no():
    m = TokenMeter()
    m.add("tool", "m", 100, 20, stage_no=2)
    m.add("tool", "m", 50, 10, stage_no=3)
    m.add("generate", "m", 200, 30, stage_no=4)
    assert m.by_stage_no(2) == (100, 20, 0)
    assert m.by_stage_no(3) == (50, 10, 0)
    assert m.by_stage_no(4) == (200, 30, 0)
    # 同类型两行互不污染（旧行为 by_stage 会给两行各自摊派总额）
    row_sums = sum(m.by_stage_no(n)[0] for n in (2, 3, 4))
    assert row_sums == m.totals()[0]


def test_by_stage_no_estimated_flag():
    m = TokenMeter()
    m.add("retrieve", "emb", 10, 0, estimated=1, stage_no=1)
    assert m.by_stage_no(1) == (10, 0, 1)
    m.add("retrieve", "emb", 5, 0, stage_no=1)          # 同行追加一笔真值
    assert m.by_stage_no(1) == (15, 0, 1)               # 任一估算 → 整行标记
    m2 = TokenMeter()
    m2.add("retrieve", "emb", 5, 0, stage_no=1)
    assert m2.by_stage_no(1) == (5, 0, 0)
    assert TokenMeter().by_stage_no(99) == (0, 0, 0)


# ---------------------------------------------------------------- 阶段行号分配

def test_stage_row_no_sequential():
    state: dict = {"stage_rows": []}
    r1 = _stage(state, "intent", "意图识别", stage_no=1)
    r2 = _stage(state, "region", "区域识别")             # 缺省取 len+1
    r3 = _stage(state, "classify", "问题分类", stage_no=3)
    assert [r["stage_no"] for r in state["stage_rows"]] == [1, 2, 3]
    assert r2["stage_no"] == 2


# ---------------------------------------------------------------- 网关透传 stage_no

def _entry(key: str, model: str) -> ModelEntry:
    return ModelEntry(key=key, base_url="http://llm.test/v1", api_keys=["sk-test"], model=model)


class _Usage:
    def __init__(self, prompt_tokens):
        self.prompt_tokens = prompt_tokens


class _EmbedResp:
    def __init__(self, usage):
        self.data = [type("D", (), {"embedding": [0.1]})()]
        self.usage = usage


class _FakeEmbedClient:
    def __init__(self, resp):
        class _Embeddings:
            async def create(self, *, model, input):
                return resp
        self.embeddings = _Embeddings()


async def test_embed_stage_no_propagates(monkeypatch):
    monkeypatch.setitem(llm._ENTRIES, "embed-test", _entry("embed-test", "emb"))
    monkeypatch.setitem(llm._EMBED_CLIENTS, "embed-test", _FakeEmbedClient(_EmbedResp(_Usage(42))))
    m = TokenMeter()
    await embed_texts(["问题"], "embed-test", meter=m, stage="retrieve", stage_no=7)
    assert m.rows[0].stage_no == 7


def _http_resp(status_code: int, body: dict):
    return type("R", (), {"status_code": status_code,
                          "json": lambda self: body, "text": ""})()


def _patch_rerank(monkeypatch, *, response=None, exc=None) -> None:
    monkeypatch.setattr(llm, "get_settings", lambda: {"rag": {"rerank_key": "rerank"}})
    monkeypatch.setitem(llm._ENTRIES, "rerank", _entry("rerank", "rr"))

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


async def test_rerank_stage_no_propagates_success(monkeypatch):
    body = {"results": [{"index": 0, "relevance_score": 0.9}], "usage": {"prompt_tokens": 30}}
    _patch_rerank(monkeypatch, response=_http_resp(200, body))
    m = TokenMeter()
    await rerank_documents("查", ["文"], top_n=1, meter=m, stage_no=5)
    assert m.rows[0].stage_no == 5


async def test_rerank_stage_no_propagates_failure(monkeypatch):
    _patch_rerank(monkeypatch, exc=httpx.ConnectError("boom"))
    m = TokenMeter()
    with pytest.raises(llm.RerankError):
        await rerank_documents("查", ["文"], top_n=1, meter=m, stage_no=6)
    assert m.rows[0].stage_no == 6
    assert m.rows[0].estimated == 1


# ---------------------------------------------------------------- 落库回填不变量

def test_persist_row_assignment_invariant():
    """阶段行回填按 stage_no 精确匹配：逐行求和 == 轮次汇总（票据验收 3 的机制层）。"""
    m = TokenMeter()
    m.add("tool", "m", 100, 20, stage_no=4)      # 工具发现后的第一轮决策调用
    m.add("tool", "m", 40, 8, stage_no=5)        # 第二轮（另一工具行）
    m.add("generate", "m", 300, 60, stage_no=6)  # 最终业务回答生成
    m.add("suggest", "m", 80, 24, stage_no=7)
    stage_rows = [
        {"stage_no": 3, "stage_type": "tool"},
        {"stage_no": 4, "stage_type": "tool"},
        {"stage_no": 5, "stage_type": "tool"},
        {"stage_no": 6, "stage_type": "generate"},
        {"stage_no": 7, "stage_type": "suggest"},
    ]
    per_row = [m.by_stage_no(r["stage_no"])[:2] for r in stage_rows]
    assert per_row == [(0, 0), (100, 20), (40, 8), (300, 60), (80, 24)]
    row_sum_in = sum(pt for pt, _ in per_row)
    row_sum_out = sum(ct for _, ct in per_row)
    assert (row_sum_in, row_sum_out) == m.totals()
