# -*- coding: utf-8 -*-
"""RAG 审计路由：召回明细浏览 + 质检标记 + badcase 导出（知识库持续优化闭环）。

闭环：检索型轮次落库召回明细（turn_recall，检索当时记录）→ 本页审"谁被召回、
得分、被重排丢谁" → 打质检标记（召回不准/答案有误/知识过旧/其他）→
前端一键把该轮 QA 预填为知识库新条目（POST /api/knowledge，复用既有入库链路）。
数据范围沿用 readable_dept_nos；页面登录即可（与轮次审计一致）。
"""
from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.audit import _dept_name_map, _source_titles, _user_map, readable_dept_nos, turn_query
from app.common.deps import LoginUser, get_login_user
from app.common.labels import (SOURCE_LABELS, RAG_FLAG_LABELS, intent_label,
                               rag_flag_label, theme_label)
from app.common.response import BizError, ok, R
from app.api.schemas import (FlagData, KnowledgeReportPage, LabelOption,
                            RagTurnDetailData, RagTurnPage)
from app.common.xlsx_export import EXPORT_ROW_LIMIT, build_xlsx, xlsx_response
from app.models import Turn, TurnFeedback, TurnRecall

router = APIRouter(prefix="/rag-audit", tags=["rag-audit"])


async def _recall_stats(turn_ids: list[int]) -> dict[int, dict]:
    """每轮召回统计：候选数 / 重排保留数。"""
    stats: dict[int, dict] = {}
    if not turn_ids:
        return stats
    rows = await TurnRecall.filter(turn_id__in=turn_ids)
    for r in rows:
        s = stats.setdefault(r.turn_id, {"recall_count": 0, "kept_count": 0})
        s["recall_count"] += 1
        s["kept_count"] += r.kept
    return stats


@router.get("/flags", response_model=R[list[LabelOption]])
async def flag_options(_: LoginUser = Depends(get_login_user)):
    """质检标记枚举（code+中文，打标控件数据源）。"""
    return ok([{"code": k, "label": v} for k, v in RAG_FLAG_LABELS.items()])


@router.get("/turns", response_model=R[RagTurnPage])
async def list_rag_turns(
    lu: LoginUser = Depends(get_login_user),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    intent: str = "rag", dept_no: str = "", flag: str = "",
    start: str = "", end: str = "", user_rating: str = "",
):
    """RAG 审计列表：默认检索型轮次，支持意图/机构/质检标记/用户反馈/时间过滤。"""
    q = await turn_query(lu, intent=intent, dept_no=dept_no, start=start, end=end)
    if flag:
        q = q.filter(rag_flag__contains=flag)
    if user_rating:
        q = q.filter(feedback__rating=user_rating)
    total = await q.count()
    rows = await q.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    user_map = await _user_map(rows)
    flag_by = {u.id: u.nick_name or u.user_name
               for u in await _user_map_flaggers(rows)} if rows else {}
    stats = await _recall_stats([t.id for t in rows])
    fb_map = {}
    if rows:
        for fb in await TurnFeedback.filter(turn_id__in=[t.id for t in rows]):
            fb_map[fb.turn_id] = fb
    return ok({
        "total": total,
        "rows": [{
            "id": t.id,
            "user": user_map.get(t.user_id, str(t.user_id)),
            "dept_no": t.dept_no, "question": t.question[:120],
            "intent": t.intent, "intent_label": intent_label(t.intent),
            "theme": t.theme, "theme_label": theme_label(t.theme),
            "status": t.status,
            "rag_flag": t.rag_flag, "rag_flag_label": rag_flag_label(t.rag_flag),
            "rag_note": t.rag_note[:80],
            "rag_flag_by": t.rag_flag_by, "rag_flag_by_name": flag_by.get(t.rag_flag_by, ""),
            "rag_flag_at": t.rag_flag_at.strftime("%Y-%m-%d %H:%M") if t.rag_flag_at else "",
            "fb_rating": fb_map[t.id].rating if t.id in fb_map else "",
            "fb_comment": fb_map[t.id].comment[:60] if t.id in fb_map else "",
            "fb_at": fb_map[t.id].updated_at.strftime("%m-%d %H:%M") if t.id in fb_map else "",
            "recall_count": stats.get(t.id, {}).get("recall_count", 0),
            "kept_count": stats.get(t.id, {}).get("kept_count", 0),
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        } for t in rows],
    })


async def _user_map_flaggers(rows) -> list:
    from app.models import SysUser
    ids = {t.rag_flag_by for t in rows if t.rag_flag_by}
    return await SysUser.filter(id__in=ids) if ids else []


@router.get("/turns/{turn_id}", response_model=R[RagTurnDetailData])
async def rag_turn_detail(turn_id: int, lu: LoginUser = Depends(get_login_user)):
    """RAG 审计详情：问题/回答/来源清单 + 召回明细（名次/得分/是否经重排保留）。"""
    turn = await Turn.get_or_none(id=turn_id)
    if not turn:
        raise BizError("轮次不存在", 404)
    scope = await readable_dept_nos(lu)
    if scope is not None and turn.dept_no not in scope:
        raise BizError("超出读范围", 403)
    recalls = await TurnRecall.filter(turn_id=turn_id).order_by("fused_rank")
    fb = await TurnFeedback.get_or_none(turn_id=turn_id)
    sources = []
    if turn.display_snapshot:
        try:
            sources = (json.loads(turn.display_snapshot) or {}).get("sources") or []
        except (json.JSONDecodeError, TypeError):
            sources = []
    return ok({
        "id": turn.id, "question": turn.question, "answer": turn.answer or "",
        "intent": turn.intent, "intent_label": intent_label(turn.intent),
        "theme": turn.theme, "theme_label": theme_label(turn.theme),
        "region": turn.region, "dept_no": turn.dept_no,
        "source_type": turn.source_type, "status": turn.status,
        "rag_flag": turn.rag_flag, "rag_note": turn.rag_note,
        "rag_flag_by": turn.rag_flag_by,
        "rag_flag_at": turn.rag_flag_at.strftime("%Y-%m-%d %H:%M:%S") if turn.rag_flag_at else "",
        "feedback": {"rating": fb.rating, "comment": fb.comment,
                     "at": fb.updated_at.strftime("%Y-%m-%d %H:%M:%S")} if fb else None,
        "sources": sources,
        "recalls": [{
            "fused_rank": r.fused_rank, "knowledge_id": r.knowledge_id, "title": r.title,
            "fused_score": r.fused_score, "kept": r.kept,
        } for r in recalls],
        "created_at": turn.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    })


class FlagBody(BaseModel):
    flags: list[str] = []
    note: str = ""


@router.post("/turns/{turn_id}/flag", response_model=R[FlagData])
async def flag_turn(turn_id: int, body: FlagBody, lu: LoginUser = Depends(get_login_user)):
    """质检标记：多选标签 + 备注，最后写入覆盖。"""
    turn = await Turn.get_or_none(id=turn_id)
    if not turn:
        raise BizError("轮次不存在", 404)
    scope = await readable_dept_nos(lu)
    if scope is not None and turn.dept_no not in scope:
        raise BizError("超出读范围", 403)
    invalid = [f for f in body.flags if f not in RAG_FLAG_LABELS]
    if invalid:
        raise BizError(f"非法标记: {invalid}")
    now = datetime.datetime.now()
    await Turn.filter(id=turn_id).update(
        rag_flag=",".join(body.flags), rag_note=(body.note or "")[:512],
        rag_flag_by=lu.user_id, rag_flag_at=now, updated_at=now,
    )
    return ok({"rag_flag": ",".join(body.flags), "rag_flag_label": rag_flag_label(body.flags)})


@router.get("/export/badcase")
async def export_badcase(
    lu: LoginUser = Depends(get_login_user),
    intent: str = "rag", dept_no: str = "", flag: str = "",
    start: str = "", end: str = "",
):
    """badcase 导出（xlsx）：已打标轮次 + 标记信息 + QA 全文 + 召回来源。"""
    """badcase 导出（xlsx）：已打质检标记或用户差评的轮次 + 标记/反馈信息 + QA 全文 + 召回来源。"""
    q = await turn_query(lu, intent=intent, dept_no=dept_no, start=start, end=end)
    down_ids = set(await TurnFeedback.filter(rating="down").values_list("turn_id", flat=True))
    candidates = await q.order_by("-id").limit(EXPORT_ROW_LIMIT + 1)
    rows = [t for t in candidates
            if (t.rag_flag or t.id in down_ids) and (not flag or flag in (t.rag_flag or ""))]
    truncated = len(candidates) > EXPORT_ROW_LIMIT
    rows = rows[:EXPORT_ROW_LIMIT]
    fb_map = {fb.turn_id: fb for fb in await TurnFeedback.filter(turn_id__in=[t.id for t in rows])}
    flaggers = {u.id: u.nick_name or u.user_name for u in await _user_map_flaggers(rows)}
    user_map = await _user_map(rows)
    dept_names = await _dept_name_map({t.dept_no for t in rows})
    headers = ["标记时间", "标记人", "质检标签", "备注", "用户反馈", "轮次ID", "时间", "用户", "机构号",
               "机构名称", "区域", "来源", "问题", "回答全文", "意图", "主题",
               "召回来源标题", "耗时(ms)", "TraceId"]
    body = [[
        t.rag_flag_at.strftime("%Y-%m-%d %H:%M:%S") if t.rag_flag_at else "",
        flaggers.get(t.rag_flag_by, str(t.rag_flag_by or "")),
        rag_flag_label(t.rag_flag), t.rag_note,
        (("👍 " if fb_map[t.id].rating == "up" else "👎 ")
         + fb_map[t.id].comment) if t.id in fb_map else "",
        t.id, t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        user_map.get(t.user_id, str(t.user_id)), t.dept_no, dept_names.get(t.dept_no, ""),
        t.region or "", SOURCE_LABELS.get(t.source_type, t.source_type),
        t.question, t.answer or "", intent_label(t.intent), theme_label(t.theme),
        _source_titles(t), t.total_ms, t.trace_id or "",
    ] for t in rows]
    name = f"RAG_badcase_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    return xlsx_response(name, build_xlsx("badcase", headers, body), truncated)


# ------------------------------------------------------------------ 知识命中报表（二期）

BIZ_TYPE_LABELS = {"qa": "问答", "doc": "文档", "common": "常识"}


async def _knowledge_report_rows(lu: LoginUser, *, dept_no: str = "", theme: str = "",
                                 biz_type: str = "", start: str = "", end: str = "",
                                 only_recalled: bool = False, only_flagged: bool = False):
    """知识条目 × 召回/质检聚合：返回 (行列表, 汇总)。

    口径：机构/主题/类型过滤作用于知识归属；时间范围作用于提问轮次（召回只发生在 rag 轮次）。
    差评关联 = 该知识被重排保留进入生成的轮次中、打了质检标记的次数（最强的"用了还被判差"信号）。
    """
    from app.models import Knowledge

    kq = Knowledge.all()
    kscope = await readable_dept_nos(lu)
    if dept_no:
        kscope = [dept_no] if (kscope is None or dept_no in kscope) else []
    if kscope is not None:
        kq = kq.filter(dept_no__in=kscope)
    if theme:
        kq = kq.filter(theme=theme)
    if biz_type:
        kq = kq.filter(biz_type=biz_type)
    kbs = await kq

    stats: dict[int, dict] = {}
    tq = await turn_query(lu, intent="rag", start=start, end=end)
    turn_ids = list(await tq.values_list("id", flat=True))
    if turn_ids:
        flagged_ids = set(await Turn.filter(id__in=turn_ids).exclude(rag_flag="").values_list("id", flat=True))
        down_ids = set(await TurnFeedback.filter(turn_id__in=turn_ids, rating="down").values_list("turn_id", flat=True))
        recalls = await TurnRecall.filter(turn_id__in=turn_ids)
        for r in recalls:
            s = stats.setdefault(r.knowledge_id, {
                "turns": set(), "rows": 0, "kept": 0, "rank_sum": 0.0, "score_sum": 0.0,
                "flag_turns": set(), "down_turns": set(), "last_at": None,
            })
            s["turns"].add(r.turn_id)
            s["rows"] += 1
            s["kept"] += r.kept
            s["rank_sum"] += r.fused_rank
            s["score_sum"] += r.fused_score
            if r.kept and r.turn_id in flagged_ids:
                s["flag_turns"].add(r.turn_id)
            if r.kept and r.turn_id in down_ids:
                s["down_turns"].add(r.turn_id)
            if r.created_at and (s["last_at"] is None or r.created_at > s["last_at"]):
                s["last_at"] = r.created_at

    dept_names = await _dept_name_map({k.dept_no for k in kbs})
    out = []
    for k in kbs:
        s = stats.get(k.id)
        if only_recalled and not s:
            continue
        flagged = len(s["flag_turns"]) if s else 0
        user_down = len(s["down_turns"]) if s else 0
        if only_flagged and not (flagged or user_down):
            continue
        recall_turns = len(s["turns"]) if s else 0
        out.append({
            "id": k.id, "title": k.title, "dept_no": k.dept_no, "dept_name": dept_names.get(k.dept_no, ""),
            "biz_type": k.biz_type, "biz_type_label": BIZ_TYPE_LABELS.get(k.biz_type, k.biz_type),
            "theme": k.theme, "theme_label": theme_label(k.theme), "sync_status": k.sync_status,
            "recall_turns": recall_turns,
            "avg_rank": round(s["rank_sum"] / s["rows"], 1) if s else None,
            "avg_score": round(s["score_sum"] / s["rows"], 4) if s else None,
            "kept_count": s["kept"] if s else 0,
            "kept_rate": round(s["kept"] / s["rows"], 3) if s else None,
            "flagged_count": flagged,
            "user_down": user_down,
            "flag_rate": round(flagged / s["kept"], 3) if s and s["kept"] else None,
            "last_recalled_at": s["last_at"].strftime("%Y-%m-%d %H:%M") if s and s["last_at"] else "",
        })
    out.sort(key=lambda x: (-x["recall_turns"], -x["kept_count"], x["id"]))
    summary = {
        "kb_total": len(kbs),
        "recalled": sum(1 for k in kbs if stats.get(k.id)),
        "never_recalled": sum(1 for k in kbs if not stats.get(k.id)),
        "flagged_linked": sum(1 for k in kbs if stats.get(k.id)
                              and (stats[k.id]["flag_turns"] or stats[k.id]["down_turns"])),
    }
    return out, summary


@router.get("/knowledge-report", response_model=R[KnowledgeReportPage])
async def knowledge_report(
    lu: LoginUser = Depends(get_login_user),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
    dept_no: str = "", theme: str = "", biz_type: str = "",
    start: str = "", end: str = "",
    only_recalled: bool = False, only_flagged: bool = False,
):
    """知识命中报表：被召回轮次/平均名次得分/保留率/差评关联——定位低质量与闲置知识。"""
    rows, summary = await _knowledge_report_rows(
        lu, dept_no=dept_no, theme=theme, biz_type=biz_type, start=start, end=end,
        only_recalled=only_recalled, only_flagged=only_flagged)
    total = len(rows)
    return ok({
        "total": total, "summary": summary,
        "rows": rows[(page - 1) * page_size: page * page_size],
    })


@router.get("/export/knowledge-report")
async def export_knowledge_report(
    lu: LoginUser = Depends(get_login_user),
    dept_no: str = "", theme: str = "", biz_type: str = "",
    start: str = "", end: str = "",
    only_recalled: bool = False, only_flagged: bool = False,
):
    """知识命中报表导出（xlsx）。"""
    rows, _ = await _knowledge_report_rows(
        lu, dept_no=dept_no, theme=theme, biz_type=biz_type, start=start, end=end,
        only_recalled=only_recalled, only_flagged=only_flagged)
    truncated = len(rows) > EXPORT_ROW_LIMIT
    headers = ["知识ID", "标题", "机构号", "机构名称", "类型", "主题", "同步状态",
               "被召回轮次", "平均融合名次", "平均融合得分", "保留次数", "保留率",
               "差评关联轮次", "差评率", "最后召回时间"]
    body = [[
        r["id"], r["title"], r["dept_no"], r["dept_name"], r["biz_type_label"], r["theme_label"],
        {0: "未同步", 1: "已同步", 2: "失败"}.get(r["sync_status"], r["sync_status"]),
        r["recall_turns"], r["avg_rank"], r["avg_score"], r["kept_count"],
        f'{int((r["kept_rate"] or 0) * 100)}%' if r["kept_rate"] is not None else "",
        r["flagged_count"],
        f'{int((r["flag_rate"] or 0) * 100)}%' if r["flag_rate"] is not None else "",
        r["last_recalled_at"],
    ] for r in rows[:EXPORT_ROW_LIMIT]]
    name = f"知识命中报表_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    return xlsx_response(name, build_xlsx("知识命中", headers, body), truncated)
