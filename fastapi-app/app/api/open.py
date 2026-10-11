# -*- coding: utf-8 -*-
"""开放接口（Open API）：面向外部接入方的问答 + 只读数据查询。

与门户共用同一 LangGraph 问答管线，差异仅在入口语义：
  - 鉴权：X-API-Key → 接入方（open_client 表），非门户 JWT；
  - 三要素：由接入方随请求传递（门户为登录态绑定），工具调用自动注入；
  - 租户：归属租户 = 接入方绑定机构；检索租户由问题区域路由决定（不可显式指定）；
  - 溯源：X-Source-System / X-Trace-Id 透传落审计，TraceId 缺省系统生成并回写响应头；
  - 会话：conversation_id 由外部传递（首次不传→创建并返回，续问回传；仅可续本接入方会话）。

路由挂载后完整路径为 /api/open/v1/*。
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import re
import time

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.api.chat import _persist, _register_turn_stream, _running, _sentinel
from app.common.response import BizError, ok, R
from app.common.trace import trace_id_of
from app.api.schemas import (OpenAccountData, OpenAskData,
                            OpenKnowledgePage, OpenTurnPage)
from app.models import Conversation, Knowledge, OpenClient, SysDept, SysUser, Turn
from app.rag import tools as mcp_tools
from app.rag.graph import get_chat_graph
from app.rag.llm import TokenMeter

router = APIRouter(prefix="/open/v1", tags=["open-api"])

# 三要素格式：身份证号 18 位（末位 X）；手机号 11 位（宽松校验）
_ID_CARD_RE = re.compile(r"^\d{17}[\dXx]$")
_PHONE_RE = re.compile(r"^1\d{10}$")

# 接入方虚拟用户（user_id 非空约束的内部载体；真实归属由 open_client_id 表达）
_SVC_USER_NAME = "openapi_svc"


async def get_open_client(x_api_key: str = Header(default="", alias="X-API-Key")) -> OpenClient:
    """接入方鉴权：X-API-Key → open_client；无 key 401，停用 403。"""
    if not x_api_key.strip():
        raise BizError("缺少 X-API-Key 请求头", 401)
    client = await OpenClient.filter(api_key=x_api_key.strip()).first()
    if not client:
        raise BizError("API Key 无效", 401)
    if client.status != "0":
        raise BizError("接入方已停用，请联系管理员", 403)
    return client


async def _svc_user_id() -> int:
    u = await SysUser.filter(user_name=_SVC_USER_NAME).first()
    if not u:
        raise BizError("开放接口虚拟用户未初始化，请先执行 scripts/init_db.py", 500)
    return u.id


def _trace_of(request: Request) -> tuple[str, str]:
    """溯源：TraceId 与门户共用 app.common.trace 规则；X-Source-System 为开放侧专属。"""
    source_system = (request.headers.get("X-Source-System") or "").strip()[:64]
    return trace_id_of(request), source_system


class OpenChatBody(BaseModel):
    question: str
    conversation_id: int | None = None
    id_card: str                      # 三要素由外部传递（与 MCP 工具 required 对齐）
    name: str = ""
    phone: str = ""
    auth_ticket: str = ""             # 预留：用户授权凭据（演示不校验，仅落审计快照）


def _validate_identity(body: OpenChatBody) -> None:
    if not _ID_CARD_RE.match(body.id_card or ""):
        raise BizError("id_card 必须为 18 位身份证号", 422)
    if body.phone and not _PHONE_RE.match(body.phone):
        raise BizError("phone 必须为 11 位手机号", 422)


async def _prepare(client: OpenClient, body: OpenChatBody,
                   trace_id: str, source_system: str) -> tuple[Conversation, Turn]:
    """会话容器与轮次登记：归属租户=接入方绑定机构；溯源列落 turn。"""
    user_id = await _svc_user_id()
    if body.conversation_id:
        conv = await Conversation.filter(id=body.conversation_id,
                                         open_client_id=client.id).first()
        if not conv:
            raise BizError("会话不存在或不属于该接入方", 404)
    else:
        title = body.question[:16] if len(body.question) > 16 else body.question
        conv = await Conversation.create(
            user_id=user_id, dept_no=client.bind_dept_no,
            open_client_id=client.id, title=title,
        )
    turn = await Turn.create(
        conversation_id=conv.id, user_id=user_id, dept_no=client.bind_dept_no,
        question=body.question, status="generating",
        source_type="open", open_client_id=client.id,
        source_system=source_system, trace_id=trace_id,
    )
    await Conversation.filter(id=conv.id).update(
        turn_count=conv.turn_count + 1, updated_at=datetime.datetime.now(),
    )
    return conv, turn


async def _build_state(client: OpenClient, body: OpenChatBody, conv: Conversation,
                       history: list[dict], emit) -> dict:
    """问答管线入参：三要素来自请求而非登录态；检索租户由区域路由节点决定。"""
    dept = await SysDept.filter(dept_no=client.bind_dept_no).first()
    return {
        "question": body.question, "history": history,
        "user_id": conv.user_id, "dept_no": client.bind_dept_no,
        "dept_name": dept.dept_name if dept else "",
        # 三要素：外部传递（姓名可空，工具按证件号查询）
        "user_id_card": body.id_card, "user_name": body.name or "",
        "user_phone": body.phone, "auth_ticket": body.auth_ticket,
        "extra_depts": [],            # 区域识别节点按目标机构重算祖先链
        "emit": emit, "meter": TokenMeter(),
    }


async def _history_of(conv: Conversation, exclude_turn_id: int) -> list[dict]:
    rows = [
        {"question": t.question, "answer": t.answer}
        async for t in Turn.filter(conversation_id=conv.id, status="done")
        .exclude(id=exclude_turn_id).order_by("-id").limit(3)
    ]
    return rows[::-1]


@router.post("/chat/stream")
async def open_chat_stream(body: OpenChatBody, request: Request,
                           client: OpenClient = Depends(get_open_client)):
    """流式问答（SSE，事件协议与门户一致：meta/stage/text/tool/sources/questions/done）。"""
    question = body.question.strip()
    if not question:
        raise BizError("question 不能为空", 422)
    _validate_identity(body)
    trace_id, source_system = _trace_of(request)
    conv, turn = await _prepare(client, body, trace_id, source_system)
    history = await _history_of(conv, turn.id)

    queue: asyncio.Queue = asyncio.Queue()
    ttft = {"ms": 0}
    t0 = time.perf_counter()
    display: dict = {}
    stream = _register_turn_stream(turn.id)
    detached = {"v": False}

    def emit(event: dict) -> None:
        if event.get("type") == "text" and not ttft["ms"]:
            ttft["ms"] = int((time.perf_counter() - t0) * 1000)
        if event.get("type") == "sources":
            display["sources"] = event.get("materials", [])
        elif event.get("type") == "questions":
            display["questions"] = event.get("questions", [])
        elif event.get("type") == "recommend":
            display["flows"] = event.get("flows", [])
        stream["buffer"].append(event)
        if not detached["v"]:
            queue.put_nowait(event)

    state = await _build_state(client, body, conv, history, emit)

    async def run_graph() -> dict:
        final: dict = {}
        cancelled = False
        try:
            final = await get_chat_graph().ainvoke(state, config={"recursion_limit": 40})
        except asyncio.CancelledError:
            cancelled = True
        except Exception as e:  # noqa: BLE001
            emit({"type": "error", "message": str(e)[:300]})
            final = {**state, "error": str(e)}
        finally:
            stream["finished"] = True
            _running.pop(turn.id, None)
            with contextlib.suppress(Exception):
                await _persist(turn, conv, final, ttft["ms"],
                               int((time.perf_counter() - t0) * 1000), cancelled, display)
            queue.put_nowait(_sentinel)
        return final

    _running[turn.id] = asyncio.create_task(run_graph())

    async def sse():
        yield "data: " + json.dumps({
            "type": "meta", "conversation_id": conv.id, "turn_id": turn.id,
            "title": conv.title, "trace_id": trace_id,
        }, ensure_ascii=False) + "\n\n"
        try:
            while True:
                item = await queue.get()
                if item is _sentinel:
                    break
                yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
        finally:
            detached["v"] = True
            with contextlib.suppress(Exception):
                yield "data: " + json.dumps({"type": "done", "turn_id": turn.id}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Trace-Id": trace_id})


@router.post("/chat/ask", response_model=R[OpenAskData])
async def open_chat_ask(body: OpenChatBody, request: Request,
                        client: OpenClient = Depends(get_open_client)):
    """同步问答：一次性返回全文+引用来源+推荐（SSE 的服务端聚合包装）。"""
    question = body.question.strip()
    if not question:
        raise BizError("question 不能为空", 422)
    _validate_identity(body)
    trace_id, source_system = _trace_of(request)
    conv, turn = await _prepare(client, body, trace_id, source_system)
    history = await _history_of(conv, turn.id)

    events: list[dict] = []
    display: dict = {}
    t0 = time.perf_counter()
    ttft = {"ms": 0}
    _register_turn_stream(turn.id)

    def emit(event: dict) -> None:
        if event.get("type") == "text" and not ttft["ms"]:
            ttft["ms"] = int((time.perf_counter() - t0) * 1000)
        if event.get("type") == "sources":
            display["sources"] = event.get("materials", [])
        elif event.get("type") == "questions":
            display["questions"] = event.get("questions", [])
        elif event.get("type") == "recommend":
            display["flows"] = event.get("flows", [])
        events.append(event)

    state = await _build_state(client, body, conv, history, emit)
    final: dict = {}
    try:
        final = await get_chat_graph().ainvoke(state, config={"recursion_limit": 40})
    except Exception as e:  # noqa: BLE001
        emit({"type": "error", "message": str(e)[:300]})
        final = {**state, "error": str(e)}
    await _persist(turn, conv, final, ttft["ms"],
                   int((time.perf_counter() - t0) * 1000), False, display)

    answer = "".join(e.get("content", "") for e in events if e.get("type") == "text")
    error = next((e.get("message") for e in events if e.get("type") == "error"), None)
    # 来源按知识条目去重（切块级材料会重复同标题）
    sources, seen_titles = [], set()
    for m in (display.get("sources") or []):
        t = m.get("title", "")
        if t in seen_titles:
            continue
        seen_titles.add(t)
        sources.append({"title": t, "dept_no": m.get("dept_code", ""),
                        "public": bool(m.get("is_public")), "score": m.get("score")})
    body = ok({
        "conversation_id": conv.id, "turn_id": turn.id, "trace_id": trace_id,
        "answer": answer, "sources": sources,
        "questions": display.get("questions") or [],
        "error": error,
    })
    return JSONResponse(body, headers={"X-Trace-Id": trace_id})


class AccountQueryBody(BaseModel):
    action: str                       # balance / loan / deposit
    id_card: str
    name: str = ""
    months: int = 6


@router.post("/account/query", response_model=R[OpenAccountData])
async def open_account_query(body: AccountQueryBody,
                             client: OpenClient = Depends(get_open_client)):
    """账户数据查询（MCP 工具的 HTTP 形态）：三要素查询，返回值已脱敏。"""
    if not _ID_CARD_RE.match(body.id_card or ""):
        raise BizError("id_card 必须为 18 位身份证号", 422)
    actions = {
        "balance": mcp_tools.query_account_balance,
        "loan": mcp_tools.query_loan_info,
        "deposit": mcp_tools.query_deposit_detail,
    }
    if body.action not in actions:
        raise BizError(f"action 须为 balance/loan/deposit", 422)
    if body.action == "balance":
        result = actions[body.action](id_card=body.id_card, name=body.name)
    elif body.action == "loan":
        result = actions[body.action](id_card=body.id_card)
    else:
        result = actions[body.action](id_card=body.id_card, months=body.months)
    from app.mock_data import mask
    return ok({"action": body.action, "id_card": mask(body.id_card), "result": result})


@router.get("/knowledge", response_model=R[OpenKnowledgePage])
async def open_knowledge(dept_no: str = "", theme: str = "", q: str = "",
                         page: int = 1, size: int = 20,
                         client: OpenClient = Depends(get_open_client)):
    """公开知识查询：只开放 is_public=1（私有知识不对外成为可枚举出口）。"""
    filters = {"is_public": 1}
    if dept_no:
        filters["dept_no"] = dept_no
    if theme:
        filters["theme"] = theme
    if q:
        filters["title__contains"] = q
    size = max(1, min(size, 100))
    qs = Knowledge.filter(**filters)
    total = await qs.count()
    rows = await qs.order_by("-id").offset((page - 1) * size).limit(size)
    return ok({
        "total": total,
        "rows": [{"id": r.id, "dept_no": r.dept_no, "biz_type": r.biz_type,
                  "title": r.title, "question": r.question, "theme": r.theme}
                 for r in rows],
    })


@router.get("/turns", response_model=R[OpenTurnPage])
async def open_turns(trace_id: str = "", page: int = 1, size: int = 20,
                     client: OpenClient = Depends(get_open_client)):
    """轮次审计查询：限本接入方产生的轮次（接入方互不可见）。"""
    filters = {"open_client_id": client.id}
    if trace_id:
        filters["trace_id"] = trace_id
    size = max(1, min(size, 100))
    qs = Turn.filter(**filters)
    total = await qs.count()
    rows = await qs.order_by("-id").offset((page - 1) * size).limit(size)
    return ok({
        "total": total,
        "rows": [{"id": t.id, "conversation_id": t.conversation_id,
                  "question": t.question[:60], "intent": t.intent, "region": t.region,
                  "theme": t.theme, "status": t.status, "trace_id": t.trace_id,
                  "source_system": t.source_system,
                  "tokens_in": t.tokens_in, "tokens_out": t.tokens_out,
                  "total_ms": t.total_ms, "created_at": str(t.created_at)}
                 for t in rows],
    })
