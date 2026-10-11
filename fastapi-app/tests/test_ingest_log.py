# -*- coding: utf-8 -*-
"""票据 05：入库计量——知识入库的消耗与结果独立登记（ADR 0003）。

验收（.scratch/observability/issues/05）：
  - 入库向量化记账进入独立流水，阶段标识为入库（不再丢弃/错标检索）
  - 同步成功与失败（含批量/对账路径）各落一行，失败行含截断错误；mark_failed 不重复记行
  - token 真值/估算口径与成本定格随行登记（依赖票据 01/04 机制）
"""
from __future__ import annotations

import pytest
from tortoise import Tortoise

from app.models import IngestLog, Knowledge
from app.rag import ingest, llm


@pytest.fixture
async def db():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["app.models"]})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


async def _kb(**kw):
    defaults = dict(dept_no="35000", biz_type="qa", title="测试知识",
                    question="标准问法", answer="标准答案")
    defaults.update(kw)
    return await Knowledge.create(**defaults)


def _fake_embed(monkeypatch, *, pt=123, estimated=0, raise_exc=None):
    """伪向量网关：按票据 01/04 口径向传入 meter 记账，并捕获 stage 标识。"""
    seen = {"stage": None}

    async def fake(texts, key, meter=None, stage="retrieve", stage_no=0):
        seen["stage"] = stage
        if raise_exc:
            raise raise_exc
        if meter:
            meter.add(stage, "ingest-model", pt, 0, estimated=estimated, stage_no=stage_no)
        return [[0.1] for _ in texts]

    monkeypatch.setattr(ingest.llm, "embed_texts", fake)
    monkeypatch.setitem(llm._ENTRIES, "ingest-key", llm.ModelEntry(
        key="ingest-key", base_url="http://llm.test/v1", api_keys=["sk"], model="ingest-model",
        price={"input": 0.001, "output": 0.0}))
    return seen


def _fake_vector(monkeypatch, *, fail=False):
    monkeypatch.setattr(ingest.vectorstore, "delete_by_knowledge", lambda kid: None)

    def bulk(**kw):
        if fail:
            raise RuntimeError("es down")
        return len(kw["chunks"])

    monkeypatch.setattr(ingest.vectorstore, "bulk_index_chunks", bulk)


# ---------------------------------------------------------------- 成功路径

async def test_sync_success_logs_ingest_row(db, monkeypatch):
    seen = _fake_embed(monkeypatch, pt=123)
    _fake_vector(monkeypatch)
    kb = await _kb()
    n = await ingest.sync_knowledge(kb.id, operator_id=7)
    assert n > 0
    log = await IngestLog.all().first()
    assert log.knowledge_id == kb.id and log.status == "done" and log.error == ""
    assert log.chunk_count == n
    assert log.tokens_in == 123 and log.tokens_estimated == 0
    assert float(log.cost) == pytest.approx(0.000123)  # 123/1000 × 0.001（票据 04 定格）
    assert log.operator_user_id == 7 and log.duration_ms >= 0
    assert seen["stage"] == "ingest"               # 修正 G1 错标：入库不再记 retrieve
    await kb.refresh_from_db(fields=["sync_status"])
    assert kb.sync_status == 1


# ---------------------------------------------------------------- 失败路径

async def test_sync_failure_logs_row_and_mark_failed_no_double(db, monkeypatch):
    _fake_embed(monkeypatch, pt=123)
    _fake_vector(monkeypatch, fail=True)
    kb = await _kb()
    with pytest.raises(RuntimeError):
        await ingest.sync_knowledge(kb.id, operator_id=9)
    log = await IngestLog.all().first()
    assert log.status == "failed" and "es down" in log.error
    assert log.tokens_in == 123                    # embed 已发生，消耗照记
    assert log.operator_user_id == 9
    # 调用方随后的 mark_failed 只更新知识行状态，不重复记流水
    await ingest.mark_failed(kb.id, "es down")
    assert await IngestLog.all().count() == 1
    await kb.refresh_from_db(fields=["sync_status", "sync_error"])
    assert kb.sync_status == 2 and "es down" in kb.sync_error


async def test_sync_failure_before_embed_logs_zero_tokens(db, monkeypatch):
    _fake_embed(monkeypatch, raise_exc=RuntimeError("embed 超时"))
    _fake_vector(monkeypatch)
    kb = await _kb()
    with pytest.raises(RuntimeError):
        await ingest.sync_knowledge(kb.id)
    log = await IngestLog.all().first()
    assert log.status == "failed" and log.tokens_in == 0
    assert "embed 超时" in log.error and log.operator_user_id == 0


async def test_empty_content_failure_logged(db, monkeypatch):
    _fake_embed(monkeypatch)
    _fake_vector(monkeypatch)
    # 标题也参与切块：title 与 content 均空才无块
    kb = await _kb(biz_type="doc", title="", content="")
    with pytest.raises(ValueError):
        await ingest.sync_knowledge(kb.id)
    log = await IngestLog.all().first()
    assert log.status == "failed" and "无可同步切块" in log.error


async def test_estimated_flag_propagates(db, monkeypatch):
    _fake_embed(monkeypatch, pt=50, estimated=1)
    _fake_vector(monkeypatch)
    kb = await _kb()
    await ingest.sync_knowledge(kb.id)
    log = await IngestLog.all().first()
    assert log.tokens_estimated == 1


# ---------------------------------------------------------------- 审查修复的回归

async def test_log_failure_does_not_mask_original_error(db, monkeypatch):
    """记账自身抛错（如 DB 故障）不得顶替原始异常。"""
    _fake_embed(monkeypatch)
    _fake_vector(monkeypatch, fail=True)
    kb = await _kb()

    async def broken_write(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(ingest, "_write_log", broken_write)
    with pytest.raises(RuntimeError, match="es down"):
        await ingest.sync_knowledge(kb.id)


async def test_sync_all_pending_marks_failed_status(db, monkeypatch):
    """批量同步失败行：计数 + 知识行置失败态（显形可重试），失败流水各记一行。"""
    _fake_embed(monkeypatch)
    monkeypatch.setattr(ingest.vectorstore, "delete_by_knowledge", lambda kid: None)
    ok_kb = await _kb(title="正常")
    bad_kb = await _kb(title="会失败")

    def bulk(knowledge_id=None, **kw):
        if knowledge_id == bad_kb.id:
            raise RuntimeError("es down")
        return len(kw["chunks"])

    monkeypatch.setattr(ingest.vectorstore, "bulk_index_chunks", bulk)
    result = await ingest.sync_all_pending(operator_id=3)
    assert result == {"ok": 1, "fail": 1}
    await ok_kb.refresh_from_db(fields=["sync_status"])
    await bad_kb.refresh_from_db(fields=["sync_status", "sync_error"])
    assert ok_kb.sync_status == 1
    assert bad_kb.sync_status == 2 and "es down" in bad_kb.sync_error
    assert await IngestLog.all().count() == 2
