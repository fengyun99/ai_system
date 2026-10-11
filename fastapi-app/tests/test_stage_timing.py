# -*- coding: utf-8 -*-
"""票据 06：阶段时间与异常列——并行可还原、失败有详情。

验收（.scratch/observability/issues/06）：
  - _stage 登记起止时间（timer 贯通），并行阶段起止重叠可还原
  - suggest/agent 末端生成等计时死角经 timer 接线（机制层）
  - 节点异常包装器登记失败行（error_detail 含堆栈、耗时到失败点）并重抛
  - _persist 落库 started_at/finished_at/error_detail 与轮次 error_detail
"""
from __future__ import annotations

import asyncio
import datetime

import pytest
from tortoise import Tortoise

from app.api.chat import _persist
from app.models import Conversation, Turn, TurnStage
from app.rag.graph import _stage, _timer, stage_error_guard
from app.rag.llm import TokenMeter


# ---------------------------------------------------------------- _timer / _stage 计时

def test_timer_records_wall_clock_datetimes():
    with _timer() as t:
        pass
    assert isinstance(t["started_at"], datetime.datetime)
    assert isinstance(t["finished_at"], datetime.datetime)
    assert t["finished_at"] >= t["started_at"]
    assert t["ms"] >= 0


def test_stage_row_carries_timer_timestamps():
    state: dict = {"stage_rows": []}
    with _timer() as t:
        pass
    row = _stage(state, "intent", "意图识别", timer=t)
    assert row["duration_ms"] == t["ms"]
    assert row["started_at"] == t["started_at"] and row["finished_at"] == t["finished_at"]


def test_stage_row_defaults_to_instant_timestamps():
    state: dict = {"stage_rows": []}
    row = _stage(state, "flow", "办理推荐")
    assert isinstance(row["started_at"], datetime.datetime)
    assert row["duration_ms"] == 0


def test_parallel_stage_rows_overlap():
    """并行两路（分类∥分化）的计时器交叠——时间线可还原并行的机制保证。"""
    t1, t2 = _timer(), _timer()
    out1 = t1.__enter__()          # classify 开始
    out2 = t2.__enter__()          # decompose 开始（classify 未结束）
    t1.__exit__(None, None, None)  # classify 结束
    t2.__exit__(None, None, None)  # decompose 结束
    assert out1["started_at"] <= out2["finished_at"]
    assert out2["started_at"] <= out1["finished_at"]   # 区间重叠
    state: dict = {"stage_rows": []}
    r1 = _stage(state, "classify", "问题分类", timer=out1)
    r2 = _stage(state, "decompose", "问题分化", timer=out2)
    assert r1["started_at"] <= r2["finished_at"] and r2["started_at"] <= r1["finished_at"]


# ---------------------------------------------------------------- 节点异常包装器

async def test_stage_error_guard_registers_failed_row_and_reraises():
    state: dict = {"stage_rows": []}

    async def boom(st):
        raise RuntimeError("模型认证失败 401")

    wrapped = stage_error_guard("intent", "意图识别")(boom)
    with pytest.raises(RuntimeError, match="401"):
        await wrapped(state)
    row = state["stage_rows"][-1]
    assert row["stage_type"] == "intent" and row["status"] == "failed"
    assert "RuntimeError" in row["error_detail"] and "401" in row["error_detail"]
    assert len(row["error_detail"]) <= 2000
    # 计时完整：登记发生在 timer 退出之后（耗时到失败点、起止俱全）
    assert row["finished_at"] is not None and row["started_at"] is not None
    assert row["duration_ms"] >= 0


async def test_stage_error_guard_passes_through_success():
    state: dict = {"stage_rows": []}

    async def fine(st):
        return {"intent": "rag"}

    wrapped = stage_error_guard("intent", "意图识别")(fine)
    assert await wrapped(state) == {"intent": "rag"}
    assert state["stage_rows"] == []   # 成功路径不额外登记


# ---------------------------------------------------------------- _persist 落库（sqlite）

@pytest.fixture
async def db():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["app.models"]})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


async def test_persist_writes_stage_timestamps_error_and_turn_error(db):
    conv = await Conversation.create(user_id=1, dept_no="35000", title="t")
    turn = await Turn.create(conversation_id=conv.id, user_id=1, dept_no="35000",
                             question="q", status="generating")
    with _timer() as t:
        await asyncio.sleep(0.001)
    stage_rows = [
        {"stage_no": 1, "stage_type": "intent", "name": "意图识别", "status": "done",
         "duration_ms": t["ms"], "started_at": t["started_at"],
         "finished_at": t["finished_at"]},
        {"stage_no": 2, "stage_type": "generate", "name": "回答生成", "status": "failed",
         "output_data": {"error": "x"}, "duration_ms": 5,
         "error_detail": "Traceback ... RuntimeError: 401"},
    ]
    await _persist(turn, conv, {
        "meter": TokenMeter(), "stage_rows": stage_rows,
        "answer": "a", "error": "模型认证失败",
        "error_detail": "Traceback ... AuthenticationError",
    }, ttft_ms=10, total_ms=20, display=None)

    stages = await TurnStage.filter(turn_id=turn.id).order_by("stage_no")
    got_start = stages[0].started_at.replace(tzinfo=None) if stages[0].started_at.tzinfo else stages[0].started_at
    got_end = stages[0].finished_at.replace(tzinfo=None) if stages[0].finished_at.tzinfo else stages[0].finished_at
    assert got_start == t["started_at"]
    assert got_end == t["finished_at"]
    assert stages[1].error_detail.startswith("Traceback")
    assert stages[1].started_at is None   # _persist 忠实透传；瞬时默认发生在 _stage 层

    await turn.refresh_from_db()
    assert turn.status == "error"
    assert "AuthenticationError" in turn.error_detail
