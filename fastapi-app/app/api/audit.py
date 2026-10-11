# -*- coding: utf-8 -*-
"""审计路由：轮次列表/阶段明细（统计审计流水）+ 仪表盘 + 数据导出。

过滤与导出共用同一套查询条件（时间范围/机构/来源/意图/状态/关键词），
数据范围统一走 readable_dept_nos（地市账号只见本地市子树）。
意图/主题的中文展示名单一来源见 app/common/labels.py。
"""
from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, Query

from app.common.deps import LoginUser, get_login_user
from app.common.labels import (STATUS_LABELS, SOURCE_LABELS, intent_label, theme_label)
from app.common.response import BizError, ok, R
from app.api.schemas import (DashboardData, DeptOption, TurnDetailData,
                            TurnPage)
from app.common.xlsx_export import EXPORT_ROW_LIMIT, build_xlsx, xlsx_response
from app.models import Conversation, IngestLog, SysDept, SysUser, Turn, TurnStage

router = APIRouter(prefix="/audit", tags=["audit"])


async def readable_dept_nos(lu: LoginUser) -> list[str] | None:
    """读范围：超管/数据范围=全部 → None(不过滤)；否则 本部门及以下子树。"""
    if lu.is_super_admin or lu.data_scope == 1:
        return None
    me = await SysDept.get(id=lu.dept_id)
    # 子树 = ancestors 含本部门 id 的所有部门
    subtree = [d async for d in SysDept.all() if f",{lu.dept_id}," in f",{d.ancestors},"]
    dept_ids = [lu.dept_id] + [d.id for d in subtree]
    rows = await SysDept.filter(id__in=dept_ids)
    return [me.dept_no] + [d.dept_no for d in rows if d.id != lu.dept_id]


def _day(s: str, *, end_of_day: bool = False) -> datetime.datetime | None:
    """日期字符串 → 过滤边界：start 当日 00:00 / end 当日 23:59:59。"""
    s = (s or "").strip()[:10]
    if not s:
        return None
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return d.replace(hour=23, minute=59, second=59) if end_of_day else d


async def turn_query(lu: LoginUser, *, intent: str = "", status: str = "", dept_no: str = "",
                     keyword: str = "", source: str = "", start: str = "", end: str = ""):
    """轮次查询构造器：列表与导出共用（含数据范围收窄）。"""
    q = Turn.all()
    scope = await readable_dept_nos(lu)
    if dept_no:
        scope = [dept_no] if (scope is None or dept_no in scope) else []
    if scope is not None:
        q = q.filter(dept_no__in=scope)
    if intent:
        q = q.filter(intent=intent)
    if status:
        q = q.filter(status=status)
    if source:
        q = q.filter(source_type=source)
    if keyword:
        q = q.filter(question__contains=keyword)
    if _day(start):
        q = q.filter(created_at__gte=_day(start))
    if _day(end, end_of_day=True):
        q = q.filter(created_at__lte=_day(end, end_of_day=True))
    return q


def _source_titles(turn: Turn) -> str:
    """来源快照里的召回来源标题（≤6，知识库+联网混合）。"""
    if not turn.display_snapshot:
        return ""
    try:
        items = (json.loads(turn.display_snapshot) or {}).get("sources") or []
    except (json.JSONDecodeError, TypeError):
        return ""
    return "；".join(str(i.get("title") or "") for i in items if i.get("title"))


async def _user_map(turns: list[Turn]) -> dict[int, str]:
    ids = {t.user_id for t in turns}
    return {u.id: u.nick_name or u.user_name for u in await SysUser.filter(id__in=ids)} if ids else {}


async def _dept_name_map(dept_nos: set[str]) -> dict[str, str]:
    dept_nos = {d for d in dept_nos if d}
    return {d.dept_no: d.dept_name for d in await SysDept.filter(dept_no__in=list(dept_nos))} if dept_nos else {}


@router.get("/depts", response_model=R[list[DeptOption]])
async def audit_depts(lu: LoginUser = Depends(get_login_user)):
    """机构下拉数据源（读范围内的在用机构，供审计/流程/RAG 审计过滤用）。"""
    scope = await readable_dept_nos(lu)
    qs = SysDept.filter(status="0")
    if scope is not None:
        qs = qs.filter(dept_no__in=scope)
    return ok([{"dept_no": d.dept_no, "dept_name": d.dept_name}
               for d in await qs.order_by("id")])


@router.get("/turns", response_model=R[TurnPage])
async def list_turns(
    lu: LoginUser = Depends(get_login_user),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    intent: str = "", status: str = "", dept_no: str = "", keyword: str = "",
    source: str = "", start: str = "", end: str = "",
):
    """轮次审计列表：意图/状态/机构/来源/时间范围/关键词筛选，读范围内收窄。"""
    q = await turn_query(lu, intent=intent, status=status, dept_no=dept_no,
                         keyword=keyword, source=source, start=start, end=end)
    total = await q.count()
    rows = await q.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    user_map = await _user_map(rows)
    return ok({
        "total": total,
        "rows": [{
            "id": t.id, "conversation_id": t.conversation_id,
            "user": user_map.get(t.user_id, str(t.user_id)),
            "dept_no": t.dept_no, "question": t.question[:120],
            "intent": t.intent, "intent_label": intent_label(t.intent),
            "region": t.region, "theme": t.theme, "theme_label": theme_label(t.theme),
            "source_type": t.source_type,
            "status": t.status, "status_label": STATUS_LABELS.get(t.status, t.status),
            "tokens_in": t.tokens_in, "tokens_out": t.tokens_out,
            "ttft_ms": t.ttft_ms, "total_ms": t.total_ms,
            "trace_id": t.trace_id, "cost": float(t.cost or 0),
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        } for t in rows],
    })


@router.get("/turns/{turn_id}", response_model=R[TurnDetailData])
async def turn_detail(turn_id: int, lu: LoginUser = Depends(get_login_user)):
    """轮次详情：问题/回答全文 + 阶段流水（输入输出/token/耗时/模型）。"""
    turn = await Turn.get(id=turn_id)
    scope = await readable_dept_nos(lu)
    if scope is not None and turn.dept_no not in scope:
        raise BizError("超出读范围", 403)
    stages = await TurnStage.filter(turn_id=turn_id).order_by("stage_no")
    return ok({
        "id": turn.id, "conversation_id": turn.conversation_id,
        "question": turn.question, "answer": turn.answer,
        "intent": turn.intent, "intent_label": intent_label(turn.intent),
        "region": turn.region, "theme": turn.theme, "theme_label": theme_label(turn.theme),
        "snapshot_id": turn.snapshot_id, "status": turn.status,
        "tokens_in": turn.tokens_in, "tokens_out": turn.tokens_out,
        "ttft_ms": turn.ttft_ms, "total_ms": turn.total_ms,
        "source_type": turn.source_type, "trace_id": turn.trace_id,
        "cost": float(turn.cost or 0),
        "error_detail": turn.error_detail or "",
        "created_at": turn.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "stages": [{
            "stage_no": s.stage_no, "stage_type": s.stage_type, "name": s.name,
            "input": json.loads(s.input_data or "{}"),
            "output": json.loads(s.output_data or "{}"),
            "status": s.status, "model": s.model,
            "tokens_in": s.tokens_in, "tokens_out": s.tokens_out,
            "tokens_estimated": s.tokens_estimated,
            "cost": float(s.cost or 0),
            "duration_ms": s.duration_ms,
            "started_at": s.started_at.strftime("%Y-%m-%d %H:%M:%S.%f") if s.started_at else "",
            "finished_at": s.finished_at.strftime("%Y-%m-%d %H:%M:%S.%f") if s.finished_at else "",
            "error_detail": s.error_detail or "",
        } for s in stages],
    })


@router.get("/dashboard", response_model=R[DashboardData])
async def dashboard(lu: LoginUser = Depends(get_login_user)):
    """管理端仪表盘：规模/意图分布/主题分布/耗时与 token 汇总（读范围内）。

    意图/主题分布返回 [{code,label,count}]，中文标签由后端单一来源提供。
    """
    scope = await readable_dept_nos(lu)
    turns_q = Turn.all()
    conv_q = Conversation.filter(status="active")
    if scope is not None:
        turns_q = turns_q.filter(dept_no__in=scope)
        conv_q = conv_q.filter(dept_no__in=scope)
    turns = await turns_q
    # 入库成本与轮次成本分开聚合（ADR 0003：入库不是轮次，两笔账各记各的）
    ingest_q = IngestLog.all()
    if scope is not None:
        ingest_q = ingest_q.filter(dept_no__in=scope)
    ingest_logs = await ingest_q
    done = [t for t in turns if t.status == "done"]
    intent_dist: dict[str, int] = {}
    theme_dist: dict[str, int] = {}
    for t in turns:
        intent_dist[t.intent or "unknown"] = intent_dist.get(t.intent or "unknown", 0) + 1
        theme_dist[t.theme or "unknown"] = theme_dist.get(t.theme or "unknown", 0) + 1
    today = datetime.date.today()
    daily: dict[str, int] = {}
    cost_today = 0.0
    ingest_cost_today = 0.0
    for t in turns:
        if t.created_at.date() == today:
            daily[t.created_at.strftime("%H:00")] = daily.get(t.created_at.strftime("%H:00"), 0) + 1
            cost_today += float(t.cost or 0)
    for lg in ingest_logs:
        if lg.created_at.date() == today:
            ingest_cost_today += float(lg.cost or 0)
    return ok({
        "conversation_count": await conv_q.count(),
        "turn_count": len(turns),
        "done_count": len(done),
        "tokens_in": sum(t.tokens_in for t in turns),
        "tokens_out": sum(t.tokens_out for t in turns),
        "avg_ttft_ms": int(sum(t.ttft_ms for t in done) / len(done)) if done else 0,
        "avg_total_ms": int(sum(t.total_ms for t in done) / len(done)) if done else 0,
        "cost_today": cost_today,
        "cost_total": sum(float(t.cost or 0) for t in turns),
        "ingest_cost_today": ingest_cost_today,
        "ingest_cost_total": sum(float(lg.cost or 0) for lg in ingest_logs),
        "intent_dist": [{"code": k, "label": intent_label(k), "count": v}
                        for k, v in sorted(intent_dist.items(), key=lambda x: -x[1])],
        "theme_dist": [{"code": k, "label": theme_label(k), "count": v}
                       for k, v in sorted(theme_dist.items(), key=lambda x: -x[1])],
        "daily": dict(sorted(daily.items())),
    })


# ------------------------------------------------------------------ 导出

def _turn_export_rows(turns: list[Turn], user_map: dict, dept_names: dict, *, with_answer: bool) -> list[list]:
    rows = []
    for t in turns:
        r = [
            t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            user_map.get(t.user_id, str(t.user_id)),
            t.dept_no, dept_names.get(t.dept_no, ""),
            t.region or "",
            SOURCE_LABELS.get(t.source_type, t.source_type),
            t.question,
        ]
        if with_answer:
            r.append(t.answer or "")
        r.extend([
            intent_label(t.intent), t.intent or "",
            theme_label(t.theme),
            "是" if t.intent == "handoff" else "否",
        ])
        if with_answer:
            r.append(_source_titles(t))
        r.extend([
            STATUS_LABELS.get(t.status, t.status),
            t.total_ms,
            t.trace_id or "",
        ])
        rows.append(r)
    return rows


@router.get("/export/turns")
async def export_turns(
    lu: LoginUser = Depends(get_login_user),
    intent: str = "", status: str = "", dept_no: str = "", keyword: str = "",
    source: str = "", start: str = "", end: str = "",
):
    """意图识别数据导出（xlsx）：与列表过滤条件一致，不含回答全文。"""
    q = await turn_query(lu, intent=intent, status=status, dept_no=dept_no,
                         keyword=keyword, source=source, start=start, end=end)
    turns = await q.order_by("-id").limit(EXPORT_ROW_LIMIT + 1)
    truncated = len(turns) > EXPORT_ROW_LIMIT
    turns = turns[:EXPORT_ROW_LIMIT]
    rows = _turn_export_rows(turns, await _user_map(turns),
                             await _dept_name_map({t.dept_no for t in turns}), with_answer=False)
    headers = ["时间", "用户", "机构号", "机构名称", "区域", "来源", "问题",
               "意图", "意图代码", "主题", "是否转人工", "状态", "耗时(ms)", "TraceId"]
    name = f"意图识别数据_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    return xlsx_response(name, build_xlsx("意图识别", headers, rows), truncated)


@router.get("/export/qa")
async def export_qa(
    lu: LoginUser = Depends(get_login_user),
    intent: str = "", status: str = "", dept_no: str = "", keyword: str = "",
    source: str = "", start: str = "", end: str = "",
):
    """对话 QA 导出（xlsx）：含回答全文与召回来源标题（按地市导出=机构过滤）。"""
    q = await turn_query(lu, intent=intent, status=status, dept_no=dept_no,
                         keyword=keyword, source=source, start=start, end=end)
    turns = await q.order_by("-id").limit(EXPORT_ROW_LIMIT + 1)
    truncated = len(turns) > EXPORT_ROW_LIMIT
    turns = turns[:EXPORT_ROW_LIMIT]
    rows = _turn_export_rows(turns, await _user_map(turns),
                             await _dept_name_map({t.dept_no for t in turns}), with_answer=True)
    headers = ["时间", "用户", "机构号", "机构名称", "区域", "来源", "问题", "回答全文",
               "意图", "意图代码", "主题", "是否转人工", "召回来源标题", "状态", "耗时(ms)", "TraceId"]
    name = f"对话QA_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    return xlsx_response(name, build_xlsx("对话QA", headers, rows), truncated)
