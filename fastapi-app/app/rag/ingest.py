# -*- coding: utf-8 -*-
"""文档入库管道：knowledge 行 → 切块 → 向量化 → ES 写入（含删除同步与全量对账）。

入库计量（ADR 0003）：每次同步的消耗与结果登记 ingest_log——成功/失败各一行，
token/成本随票据 01/04 口径定格；失败也记账后向调用方重抛。
"""
from __future__ import annotations

import asyncio
import contextlib
import time

from app.models import IngestLog, Knowledge
from app.rag import llm, splitter, vectorstore
from app.rag.llm import TokenMeter


def _elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


async def _write_log(kb: Knowledge, *, chunk_count: int, meter: TokenMeter,
                     duration_ms: int, status: str, error: str, operator_id: int) -> None:
    pt, ct = meter.totals()
    await IngestLog.create(
        knowledge_id=kb.id, title=(kb.title or "")[:128], dept_no=kb.dept_no,
        chunk_count=chunk_count, tokens_in=pt, tokens_out=ct,
        tokens_estimated=1 if any(r.estimated for r in meter.rows) else 0,
        cost=meter.total_cost(), duration_ms=duration_ms,
        status=status, error=error[:500], operator_user_id=operator_id,
    )


async def sync_knowledge(knowledge_id: int, operator_id: int = 0) -> int:
    """把一条 knowledge 同步到 ES（先删后写，幂等）。返回切块数；抛错由调用方置失败态。

    成功与失败均登记一行入库计量流水；operator_id 为触发同步的用户（0=系统）。
    """
    kb = await Knowledge.get(id=knowledge_id)
    meter = TokenMeter()
    chunks: list = []
    t0 = time.perf_counter()
    try:
        vectorstore.delete_by_knowledge(knowledge_id)

        if kb.biz_type == "qa":
            chunks = splitter.chunk_qa(kb.question, kb.answer)
        else:
            body = kb.content or ""
            chunks = splitter.chunk_document(f"{kb.title}\n{body}")

        if not chunks:
            raise ValueError("知识内容为空，无可同步切块")

        vectors = await llm.embed_texts(chunks, _embed_key(), meter, stage="ingest")
        n = vectorstore.bulk_index_chunks(
            knowledge_id=kb.id, title=kb.title, dept_no=kb.dept_no,
            biz_type=kb.biz_type, theme=kb.theme, is_public=kb.is_public,
            chunks=chunks, vectors=vectors,
        )
        kb.sync_status = 1
        kb.sync_error = ""
        await kb.save(update_fields=["sync_status", "sync_error"])
        await _write_log(kb, chunk_count=n, meter=meter, duration_ms=_elapsed_ms(t0),
                         status="done", error="", operator_id=operator_id)
        return n
    except Exception as e:  # noqa: BLE001 失败也记账（消耗照记），异常照抛由调用方处置
        # 记账尽力而为：记账自身失败（如 DB 故障）不得顶替原始异常
        with contextlib.suppress(Exception):
            await _write_log(kb, chunk_count=len(chunks), meter=meter,
                             duration_ms=_elapsed_ms(t0), status="failed",
                             error=str(e), operator_id=operator_id)
        raise


async def mark_failed(knowledge_id: int, error: str) -> None:
    """置知识行失败态（不记流水——失败行已由 sync_knowledge 落过，避免双记）。"""
    await Knowledge.filter(id=knowledge_id).update(sync_status=2, sync_error=error[:500])


async def sync_all_pending(operator_id: int = 0) -> dict:
    """批量同步未同步/失败行（管理端"一键同步"与启动自愈共用）。"""
    rows = await Knowledge.filter(sync_status__in=[0, 2])
    ok = fail = 0
    for row in rows:
        try:
            await sync_knowledge(row.id, operator_id=operator_id)
            ok += 1
        except Exception as e:  # noqa: BLE001 单行失败不阻塞批量（失败行已记流水）
            await mark_failed(row.id, str(e))
            fail += 1
    return {"ok": ok, "fail": fail}


async def reconcile() -> dict:
    """全量对账：库有索引无补推，库无索引有删除。"""
    es_ids = set(vectorstore.mget_all_knowledge_ids())
    db_ids = set(await Knowledge.all().values_list("id", flat=True))
    push = sorted(db_ids - es_ids)
    drop = sorted(es_ids - db_ids)
    for kid in push:
        try:
            await sync_knowledge(kid)          # 启动对账 = 系统操作者（0）
        except Exception as e:  # noqa: BLE001
            await mark_failed(kid, str(e))     # ES 缺失重推失败须显形（不能停在"已同步"）
    for kid in drop:
        vectorstore.delete_by_knowledge(kid)
    return {"pushed": len(push), "dropped": len(drop)}


def _embed_key() -> str:
    from app.settings import get_settings
    return get_settings()["rag"].get("embeddings_key", "qwen")
