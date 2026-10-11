# -*- coding: utf-8 -*-
"""票据 04：模型单价与成本定格。

验收（.scratch/observability/issues/04）：
  - 模型配置条目支持单价（元/1K tokens，输入/输出两口价），加载后可按模型名查询
  - 落库时定格成本：单轮成本 == 各阶段行成本之和（ADR 0002：调价不改历史）
  - 响应契约同步：审计/仪表盘 schema 覆盖序列化字段（extra=forbid 下漏声明即运行时 500）
"""
from __future__ import annotations

import json

import pytest

from app.rag import llm
from app.rag.llm import TokenMeter, load_model_config, price_of
from app.api.schemas import DashboardData, StageRow, TurnDetailData, TurnRow


def _write_cfg(tmp_path, *, price_in=0.001, price_out=0.002, include_price=True):
    entry = {
        "key": "cost-test", "base_url": "http://llm.test/v1",
        "api_key": ["sk-plain"], "model": "cost-model",
    }
    if include_price:
        entry["price"] = {"input": price_in, "output": price_out}
    p = tmp_path / "model-config.json"
    p.write_text(json.dumps([entry]), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 单价加载与查询

def test_price_loaded_from_config(tmp_path):
    entries = load_model_config(_write_cfg(tmp_path))
    assert entries["cost-test"].price == {"input": 0.001, "output": 0.002}


def test_price_of_by_model_name(tmp_path):
    load_model_config(_write_cfg(tmp_path))
    assert price_of("cost-model") == (0.001, 0.002)
    assert price_of("no-such-model") == (0.0, 0.0)


def test_missing_price_entry_means_zero(tmp_path):
    load_model_config(_write_cfg(tmp_path, include_price=False))
    m = TokenMeter()
    m.add("generate", "cost-model", 1000, 1000, stage_no=1)
    assert m.total_cost() == 0


# ---------------------------------------------------------------- 成本计算与定格语义

def test_meter_cost_by_stage_no(tmp_path):
    load_model_config(_write_cfg(tmp_path))       # 0.001/1K 入， 0.002/1K 出
    m = TokenMeter()
    m.add("generate", "cost-model", 2000, 1000, stage_no=1)   # 2×0.001 + 1×0.002 = 0.004
    m.add("tool", "no-such-model", 5000, 0, stage_no=2)        # 单价缺失 → 0
    assert m.cost_by_stage_no(1) == pytest.approx(0.004)
    assert m.cost_by_stage_no(2) == 0
    assert m.total_cost() == pytest.approx(0.004)
    # 行成本之和 == 轮次总成本
    assert sum(m.cost_by_stage_no(n) for n in (1, 2)) == pytest.approx(m.total_cost())


def test_cost_frozen_at_persist_time(tmp_path):
    """ADR 0002：定格发生在落库（调用 cost）时点——调价后新计算用新价，已定格值不变。"""
    load_model_config(_write_cfg(tmp_path))
    m = TokenMeter()
    m.add("generate", "cost-model", 1000, 0, stage_no=1)
    frozen = m.cost_by_stage_no(1)
    assert frozen == pytest.approx(0.001)
    load_model_config(_write_cfg(tmp_path, price_in=0.01))    # 调价 10 倍
    assert m.cost_by_stage_no(1) == pytest.approx(0.01)       # 新落库按现价
    assert frozen == pytest.approx(0.001)                     # 已定格的历史不被重算


def test_unattributed_rows_count_in_total_only(tmp_path):
    """已知边界：stage_no=0 的未归属计量计入轮次总额、无阶段行承载
    （正常管线所有调用方都传 stage_no，此为防御口径的显式记录）。"""
    load_model_config(_write_cfg(tmp_path))
    m = TokenMeter()
    m.add("generate", "cost-model", 1000, 0, stage_no=1)
    m.add("tool", "cost-model", 500, 0, stage_no=0)
    assert m.cost_by_stage_no(1) == pytest.approx(0.001)
    assert m.cost_by_stage_no(0) == pytest.approx(0.0005)
    assert m.total_cost() == pytest.approx(0.0015)


# ---------------------------------------------------------------- 响应契约同步（防 extra=forbid 丢字段/500）

def test_audit_schemas_cover_serialized_fields():
    stage = StageRow(stage_no=1, stage_type="retrieve", name="混合检索",
                     input={}, output={}, status="done", model="m",
                     tokens_in=10, tokens_out=0, tokens_estimated=1,
                     cost=0.001, duration_ms=5,
                     started_at="2026-10-11 10:00:00.123456",
                     finished_at="2026-10-11 10:00:00.130000",
                     error_detail="")
    assert stage.cost == 0.001 and stage.tokens_estimated == 1
    detail = TurnDetailData(
        id=1, conversation_id=1, question="q", answer="a",
        intent="rag", intent_label="知识问答", region="", theme="other",
        theme_label="其他", snapshot_id="", status="done",
        tokens_in=1, tokens_out=2, ttft_ms=10, total_ms=20,
        source_type="portal", trace_id="t1", cost=0.002, error_detail="",
        created_at="2026-10-11 10:00:00", stages=[stage])
    assert detail.cost == 0.002
    row = TurnRow(
        id=1, conversation_id=1, user="u", dept_no="35000", question="q",
        intent="rag", intent_label="知识问答", region="", theme="other",
        theme_label="其他", source_type="portal", status="done", status_label="完成",
        tokens_in=1, tokens_out=2, ttft_ms=10, total_ms=20,
        trace_id="t1", cost=0.002, created_at="2026-10-11 10:00:00")
    assert row.trace_id == "t1"
    dash = DashboardData(
        conversation_count=1, turn_count=2, done_count=1, tokens_in=10, tokens_out=5,
        avg_ttft_ms=100, avg_total_ms=1000, intent_dist=[], theme_dist=[], daily={},
        cost_today=0.5, cost_total=1.2,
        ingest_cost_today=0.05, ingest_cost_total=0.3)
    assert dash.cost_today == 0.5 and dash.cost_total == 1.2
    assert dash.ingest_cost_total == 0.3
