# -*- coding: utf-8 -*-
"""知识库路由：CRUD + 入库同步（切块/向量化/ES 写入）+ 全量对账。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.common.deps import LoginUser, get_login_user, require_perm
from app.common.response import BizError, ok, R
from app.api.schemas import (IngestLogRow, KnowledgePage, KnowledgeSaveData,
                            ReconcileData, SyncAllData, SyncOneData)
from app.models import IngestLog, Knowledge
from app.rag import ingest, vectorstore
from app.api.audit import readable_dept_nos

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def writable_dept_nos(lu: LoginUser) -> list[str]:
    """可写集＝权限合集（数据范围=全部 → 全机构可写）。"""
    if lu.is_super_admin or lu.data_scope == 1:
        return [d.dept_no async for d in __import__("app.models", fromlist=["SysDept"]).SysDept.all()]
    return [lu.dept_no]


@router.get("/list", response_model=R[KnowledgePage])
async def list_knowledge(
    lu: LoginUser = Depends(get_login_user),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    dept_no: str = "", biz_type: str = "", keyword: str = "",
):
    q = Knowledge.all()
    scope = await readable_dept_nos(lu)
    if dept_no:
        if scope is not None and dept_no not in scope:
            return ok({"total": 0, "rows": []})
        q = q.filter(dept_no=dept_no)
    elif scope is not None:
        q = q.filter(dept_no__in=scope)
    if biz_type:
        q = q.filter(biz_type=biz_type)
    if keyword:
        q = q.filter(title__contains=keyword)
    total = await q.count()
    rows = await q.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return ok({
        "total": total,
        "rows": [{
            "id": r.id, "dept_no": r.dept_no, "biz_type": r.biz_type, "title": r.title,
            "question": r.question[:80], "theme": r.theme, "is_public": r.is_public,
            "sync_status": r.sync_status, "sync_error": r.sync_error[:120],
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
        } for r in rows],
    })


class KnowledgeBody(BaseModel):
    dept_no: str
    biz_type: str = "qa"            # qa | doc | common
    title: str
    question: str = ""
    answer: str = ""
    content: str = ""
    theme: str = "other"
    is_public: int = 0


@router.post("", response_model=R[KnowledgeSaveData])
async def create_knowledge(body: KnowledgeBody, lu: LoginUser = Depends(require_perm("kb:add"))):
    if body.dept_no not in await writable_dept_nos(lu):
        raise BizError("目标机构不在可写集内", 403)
    if body.biz_type == "qa" and (not body.question or not body.answer):
        raise BizError("问答类型需填写标准问法与答案")
    if body.biz_type != "qa" and not body.content:
        raise BizError("文档/常识类型需填写正文内容")
    row = await Knowledge.create(
        dept_no=body.dept_no, biz_type=body.biz_type, title=body.title,
        question=body.question, answer=body.answer, content=body.content,
        theme=body.theme, is_public=body.is_public, created_by=lu.user_id,
    )
    try:
        await ingest.sync_knowledge(row.id, operator_id=lu.user_id)
    except Exception as e:  # noqa: BLE001 入库失败显形为未同步行，可重试（失败行已记流水）
        await ingest.mark_failed(row.id, str(e))
    await row.refresh_from_db()
    return ok({"id": row.id, "sync_status": row.sync_status, "sync_error": row.sync_error})


@router.put("/{knowledge_id}", response_model=R[KnowledgeSaveData])
async def update_knowledge(knowledge_id: int, body: KnowledgeBody,
                           lu: LoginUser = Depends(require_perm("kb:edit"))):
    row = await Knowledge.get(id=knowledge_id)
    if row.dept_no not in await writable_dept_nos(lu):
        raise BizError("目标机构不在可写集内", 403)
    row.dept_no, row.biz_type, row.title = body.dept_no, body.biz_type, body.title
    row.question, row.answer, row.content = body.question, body.answer, body.content
    row.theme, row.is_public = body.theme, body.is_public
    row.sync_status, row.sync_error = 0, ""
    await row.save()
    try:
        await ingest.sync_knowledge(row.id, operator_id=lu.user_id)
    except Exception as e:  # noqa: BLE001
        await ingest.mark_failed(row.id, str(e))
    await row.refresh_from_db()
    return ok({"id": row.id, "sync_status": row.sync_status, "sync_error": row.sync_error})


@router.delete("/{knowledge_id}", response_model=R[None])
async def delete_knowledge(knowledge_id: int, lu: LoginUser = Depends(require_perm("kb:remove"))):
    row = await Knowledge.get(id=knowledge_id)
    if row.dept_no not in await writable_dept_nos(lu):
        raise BizError("目标机构不在可写集内", 403)
    vectorstore.delete_by_knowledge(row.id)
    await row.delete()
    return ok(msg="已删除（索引已同步清除）")


@router.post("/sync/{knowledge_id}", response_model=R[SyncOneData])
async def sync_one(knowledge_id: int, lu: LoginUser = Depends(require_perm("kb:edit"))):
    try:
        n = await ingest.sync_knowledge(knowledge_id, operator_id=lu.user_id)
        return ok({"chunks": n})
    except Exception as e:  # noqa: BLE001
        await ingest.mark_failed(knowledge_id, str(e))
        raise BizError(f"同步失败: {e}")


@router.post("/sync_all", response_model=R[SyncAllData])
async def sync_all(lu: LoginUser = Depends(require_perm("kb:edit"))):
    return ok(await ingest.sync_all_pending(operator_id=lu.user_id))


@router.post("/reconcile", response_model=R[ReconcileData])
async def reconcile(lu: LoginUser = Depends(require_perm("kb:edit"))):
    """全量对账：库有索引无补推，库无索引有删除。"""
    return ok(await ingest.reconcile())


@router.get("/ingest-logs/{knowledge_id}", response_model=R[list[IngestLogRow]])
async def ingest_logs(knowledge_id: int, lu: LoginUser = Depends(get_login_user)):
    """入库计量记录：该条目最近 20 次同步的消耗/耗时/结果（ADR 0003）。

    按流水自带 dept_no 做读范围过滤——知识条目删除后历史流水仍可查（成本已发生）。
    """
    scope = await readable_dept_nos(lu)
    logs_q = IngestLog.filter(knowledge_id=knowledge_id)
    if scope is not None:
        logs_q = logs_q.filter(dept_no__in=scope)
    logs = await logs_q.order_by("-id").limit(20)
    return ok([{
        "id": lg.id, "knowledge_id": lg.knowledge_id, "title": lg.title,
        "dept_no": lg.dept_no, "chunk_count": lg.chunk_count,
        "tokens_in": lg.tokens_in, "tokens_out": lg.tokens_out,
        "tokens_estimated": lg.tokens_estimated, "cost": float(lg.cost or 0),
        "duration_ms": lg.duration_ms, "status": lg.status, "error": lg.error,
        "operator_user_id": lg.operator_user_id,
        "created_at": lg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    } for lg in logs])
