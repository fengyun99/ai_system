# -*- coding: utf-8 -*-
"""聊天路由：SSE 流式问答（LangGraph 全管线）+ 停止 + 会话历史。"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import time
import traceback

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.asyncio import Redis as AIORedis

from app.common.deps import LoginUser, get_login_user, resolve_ancestor_chain
from app.common.response import BizError, ok, R
from app.common.trace import trace_id_of
from app.api.schemas import (ChatProgressData, ConversationDetailData,
                            ConversationItem, FeedbackData, HandoffData,
                            StopData)
from app.models import Conversation, Turn, TurnFeedback, TurnRecall, TurnStage
from app.rag.graph import MAX_ERROR_DETAIL, get_chat_graph
from app.rag.llm import TokenMeter
from app.settings import get_settings

router = APIRouter(tags=["chat"])

_sentinel = object()
_running: dict[int, asyncio.Task] = {}       # turn_id → graph 任务（进程内停止面）
_turn_streams: dict[int, dict] = {}          # turn_id → {buffer, finished}（断线重连回放源）


def _register_turn_stream(turn_id: int) -> dict:
    entry = {"buffer": [], "finished": False}
    _turn_streams[turn_id] = entry
    # 防泄漏：只保留最近 200 个轮次缓冲
    if len(_turn_streams) > 200:
        for k in list(_turn_streams)[: len(_turn_streams) - 200]:
            _turn_streams.pop(k, None)
    return entry


class ChatBody(BaseModel):
    question: str
    conversation_id: int | None = None


def _redis() -> AIORedis | None:
    try:
        s = get_settings()["redis"]
        # protocol=2：兼容本机 Redis 3.x（redis-py 默认 RESP3 握手 HELLO 需 6.0+）
        return AIORedis(host=s["host"], port=int(s["port"]), password=s["password"] or None,
                        decode_responses=True, protocol=2)
    except Exception:  # noqa: BLE001 Redis 不可用时停止信号退化为进程内
        return None


@router.post("/chat/stream")
async def chat_stream(body: ChatBody, request: Request,
                      lu: LoginUser = Depends(get_login_user)):
    question = body.question.strip()
    if not question:
        raise BizError("请输入问题")

    # 会话容器（无则新建）；登记归属=提问人机构
    if body.conversation_id:
        conv = await Conversation.filter(id=body.conversation_id, user_id=lu.user_id).first()
        if not conv:
            raise BizError("会话不存在", 404)
        # 流程门控：办理中的会话禁止提问，需先完成或取消流程
        from app.flow_engine import get_running
        running = await get_running(conv.id)
        if running:
            raise BizError("当前有进行中的业务流程，请先完成流程或取消后再提问", 409)
    else:
        conv = await Conversation.create(
            user_id=lu.user_id, dept_no=lu.dept_no,
            title=question[:16] if len(question) > 16 else question,
        )
    turn = await Turn.create(
        conversation_id=conv.id, user_id=lu.user_id, dept_no=lu.dept_no,
        question=question, status="generating",
        trace_id=trace_id_of(request),   # 溯源全入口统一：与开放接口同一规则
    )
    await Conversation.filter(id=conv.id).update(
        turn_count=conv.turn_count + 1,
        updated_at=datetime.datetime.now(),
    )

    history = [
        {"question": t.question, "answer": t.answer}
        async for t in Turn.filter(conversation_id=conv.id, status="done")
        .exclude(id=turn.id).order_by("-id").limit(3)
    ][::-1]

    queue: asyncio.Queue = asyncio.Queue()
    ttft = {"ms": 0}
    t0 = time.perf_counter()
    display: dict = {}          # 展示要素快照（历史原样恢复：来源/相关推荐/办理推荐）
    stream = _register_turn_stream(turn.id)
    detached = {"v": False}     # 客户端断开后只写缓冲、不再投递实时队列

    def emit(event: dict) -> None:
        if event.get("type") == "text" and not ttft["ms"]:
            ttft["ms"] = int((time.perf_counter() - t0) * 1000)
        if event.get("type") == "sources":
            display["sources"] = event.get("materials", [])
        elif event.get("type") == "question":
            display["questions"] = event.get("questions", [])
        elif event.get("type") == "recommend":
            display["flows"] = event.get("flows", [])
        stream["buffer"].append(event)
        if not detached["v"]:
            queue.put_nowait(event)

    state = {
        "question": question, "history": history,
        "user_id": lu.user_id, "dept_no": lu.dept_no, "dept_name": lu.dept_name,
        "user_id_card": lu.id_card, "user_name": lu.nick_name,
        "extra_depts": await resolve_ancestor_chain(lu.dept_no),
        "emit": emit, "meter": TokenMeter(),
    }

    async def run_graph() -> dict:
        """整轮执行体：完成/停止/异常统一在此落库——客户端断开不影响执行（断线重连语义）。"""
        final: dict = {}
        cancelled = False
        try:
            final = await get_chat_graph().ainvoke(state, config={"recursion_limit": 40})
        except asyncio.CancelledError:
            cancelled = True        # 仅显式停止（/chat/stop）会取消任务
        except Exception as e:      # noqa: BLE001 管线异常以 error 事件透出，轮次置错
            msg = f"{e}"
            if "401" in msg or "Authentication Fails" in msg or "invalid_api_key" in msg:
                msg = ("模型服务认证失败：请把有效的 DeepSeek key 明文填入 config/model-config.json "
                       "的 api_key 数组（首次启动自动加密），scripts/check_models.py 可自检")
            emit({"type": "error", "message": msg[:300]})
            final = {**state, "error": str(e),
                     "error_detail": traceback.format_exc()[:MAX_ERROR_DETAIL]}
        finally:
            stream["finished"] = True
            _running.pop(turn.id, None)
            with contextlib.suppress(Exception):
                await _persist(turn, conv, final, ttft["ms"],
                               int((time.perf_counter() - t0) * 1000), cancelled, display)
            queue.put_nowait(_sentinel)
        return final

    graph_task = asyncio.create_task(run_graph())
    _running[turn.id] = graph_task

    async def sse():
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conv.id, 'turn_id': turn.id, 'trace_id': turn.trace_id, 'title': conv.title}, ensure_ascii=False)}\n\n"
        try:
            while True:
                item = await queue.get()
                if item is _sentinel:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            # 断线≠停止：客户端离开只解除实时投递，执行与落库由 run_graph 收尾（可经 resume 续看）
            detached["v"] = True
            try:
                yield f"data: {json.dumps({'type': 'done', 'turn_id': turn.id}, ensure_ascii=False)}\n\n"
            except Exception:  # noqa: BLE001 断开后无法再发帧，忽略
                pass

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _persist(turn: Turn, conv: Conversation, final: dict, ttft_ms: int, total_ms: int,
                  cancelled: bool = False, display: dict | None = None) -> None:
    """轮次落库：阶段明细 + 汇总（token/耗时）。"""
    meter: TokenMeter = final.get("meter") or TokenMeter()
    rows = final.get("stage_rows") or []
    if rows:
        # 行级回填：token/估算口径/成本按 stage_no 精确归属到本行（成本落库即定格,ADR 0002）
        stage_models = []
        for i, r in enumerate(rows):
            no = r.get("stage_no") or i + 1
            tin, tout, est = meter.by_stage_no(no)
            stage_models.append(TurnStage(
                turn_id=turn.id, stage_no=no, stage_type=r["stage_type"],
                name=r.get("name", ""),
                input_data=json.dumps(r.get("input_data", {}), ensure_ascii=False),
                output_data=json.dumps(r.get("output_data", {}), ensure_ascii=False),
                status=r.get("status", "done"), model=r.get("model", ""),
                tokens_in=tin, tokens_out=tout, tokens_estimated=est,
                cost=meter.cost_by_stage_no(no),
                duration_ms=r.get("duration_ms", 0),
                started_at=r.get("started_at"), finished_at=r.get("finished_at"),
                error_detail=(r.get("error_detail") or "")[:MAX_ERROR_DETAIL],
            ))
        await TurnStage.bulk_create(stage_models)
    pt, ct = meter.totals()
    # 召回明细（RAG 审计）：检索型轮次才有 recall_audit；门户与开放接口共用本落库点
    recall = (final.get("recall_audit") or [])[:20]
    if recall:
        kept = set(final.get("recall_kept") or [])
        await TurnRecall.bulk_create([
            TurnRecall(turn_id=turn.id, knowledge_id=r.get("knowledge_id") or 0,
                       title=(r.get("title") or "")[:128], fused_rank=int(r.get("rank") or 0),
                       fused_score=float(r.get("score") or 0),
                       kept=1 if r.get("chunk_id") in kept else 0)
            for r in recall])
    status = "interrupted" if cancelled else ("error" if final.get("error") else "done")
    await Turn.filter(id=turn.id).update(
        answer=(final.get("answer") or "")[:60000],
        intent=final.get("intent", "") or "", region=final.get("region_name", "") or "",
        theme=final.get("theme", "") or "", snapshot_id=final.get("snapshot_id", "") or "",
        status=status,
        tokens_in=pt, tokens_out=ct, ttft_ms=ttft_ms, total_ms=total_ms,
        cost=meter.total_cost(),
        error_detail=(final.get("error_detail") or "")[:MAX_ERROR_DETAIL],
        display_snapshot=json.dumps(display or {}, ensure_ascii=False) if display else "",
        updated_at=datetime.datetime.now(),
    )
    await Conversation.filter(id=conv.id).update(updated_at=datetime.datetime.now())


@router.get("/chat/progress/{turn_id}", response_model=R[ChatProgressData])
async def chat_progress(turn_id: int, lu: LoginUser = Depends(get_login_user)):
    """轮次运行状态（前端断线后判定：续流 resume / 还是直接回读历史）。"""
    turn = await Turn.get_or_none(id=turn_id, user_id=lu.user_id)
    if not turn:
        raise BizError("轮次不存在", 404)
    entry = _turn_streams.get(turn_id)
    if entry is not None:
        return ok({"running": not entry["finished"], "status": turn.status})
    if turn.status == "generating":
        # 服务重启等导致的悬挂 generating：按中断收口，前端回读历史即可
        await Turn.filter(id=turn_id).update(status="interrupted")
        return ok({"running": False, "status": "interrupted"})
    return ok({"running": False, "status": turn.status})


@router.get("/chat/resume/{turn_id}")
async def chat_resume(turn_id: int, lu: LoginUser = Depends(get_login_user)):
    """断线重连：回放该轮全部缓冲事件；仍在生成则续流到结束。

    客户端断开不影响服务端执行（断线≠停止），事件在进程内缓冲，重连后从头发送。
    """
    turn = await Turn.get_or_none(id=turn_id, user_id=lu.user_id)
    if not turn:
        raise BizError("轮次不存在", 404)
    entry = _turn_streams.get(turn_id)

    async def replay():
        if entry is None:
            # 无缓冲（已完成落库或服务重启）：按库内终态回放全文
            if turn.answer:
                yield f"data: {json.dumps({'type': 'text', 'content': turn.answer}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'turn_id': turn.id}, ensure_ascii=False)}\n\n"
            return
        idx = 0
        deadline = time.time() + 300          # 续流上限 5 分钟
        while True:
            buf = entry["buffer"]
            while idx < len(buf):
                yield f"data: {json.dumps(buf[idx], ensure_ascii=False)}\n\n"
                idx += 1
            if entry["finished"]:
                break
            if time.time() > deadline:
                yield f"data: {json.dumps({'type': 'error', 'message': '续流超时，请刷新查看结果'}, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.15)
        yield f"data: {json.dumps({'type': 'done', 'turn_id': turn.id}, ensure_ascii=False)}\n\n"
    return StreamingResponse(replay(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class StopBody(BaseModel):
    turn_id: int


@router.post("/chat/stop", response_model=R[StopData])
async def chat_stop(body: StopBody, lu: LoginUser = Depends(get_login_user)):
    """用户停止：进程内任务取消 + Redis 跨实例信号（键 stop:{turn_id}，TTL 60s）。"""
    task = _running.get(body.turn_id)
    accepted = bool(task and not task.done())
    if accepted:
        task.cancel()
    r = _redis()
    if r:
        try:
            await r.set(f"stop:{body.turn_id}", "1", ex=60)
            await r.aclose()
        except Exception:  # noqa: BLE001
            pass
    return ok({"accepted": accepted})


class HandoffBody(BaseModel):
    conversation_id: int | None = None
    reason: str = ""


class FeedbackBody(BaseModel):
    turn_id: int
    rating: str                 # up=点赞 / down=差评
    comment: str = ""


@router.post("/chat/feedback", response_model=R[FeedbackData])
async def chat_feedback(body: FeedbackBody, lu: LoginUser = Depends(get_login_user)):
    """回答反馈：点赞/差评 + 修改意见（每轮一条，重评覆盖；仅限本人轮次）。

    反馈进入 RAG 审计的差评关联口径（列表过滤/知识命中报表/badcase 导出）。
    """
    if body.rating not in ("up", "down"):
        raise BizError("rating 只能是 up/down")
    turn = await Turn.get_or_none(id=body.turn_id, user_id=lu.user_id)
    if not turn:
        raise BizError("轮次不存在", 404)
    comment = (body.comment or "")[:512]
    fb = await TurnFeedback.get_or_none(turn_id=body.turn_id)
    if fb:
        await TurnFeedback.filter(id=fb.id).update(
            rating=body.rating, comment=comment, updated_at=datetime.datetime.now())
    else:
        await TurnFeedback.create(turn_id=body.turn_id, user_id=lu.user_id,
                                  rating=body.rating, comment=comment)
    return ok({"turn_id": body.turn_id, "rating": body.rating, "comment": comment})


@router.post("/chat/handoff", response_model=R[HandoffData])
async def chat_handoff(body: HandoffBody, lu: LoginUser = Depends(get_login_user)):
    """转人工：登记转接请求（轮次审计留痕），返回坐席提示。"""
    text = ("已收到您的转人工请求，正在为您接入在线坐席（服务时间 9:00-17:00，"
            "预计等待 1 分钟）。也可直接拨打 12329 服务热线。")
    if body.conversation_id:
        conv = await Conversation.filter(id=body.conversation_id, user_id=lu.user_id).first()
        if conv:
            turn = await Turn.create(
                conversation_id=conv.id, user_id=lu.user_id, dept_no=lu.dept_no,
                question=f"[转人工] {body.reason[:80]}", answer=text, intent="handoff",
                status="done",
            )
            await TurnStage.create(
                turn_id=turn.id, stage_no=1, stage_type="handoff", name="人工转接登记",
                input_data=json.dumps({"reason": body.reason[:120]}, ensure_ascii=False),
                output_data=json.dumps({"queue": "online", "sla": "9:00-17:00"}, ensure_ascii=False),
            )
            await Conversation.filter(id=conv.id).update(turn_count=conv.turn_count + 1)
    return ok({"text": text})


# ---------------- 会话历史（用户端） ----------------

@router.get("/conversations", response_model=R[list[ConversationItem]])
async def list_conversations(lu: LoginUser = Depends(get_login_user)):
    rows = await Conversation.filter(user_id=lu.user_id, status="active").order_by("-updated_at").limit(50)
    return ok([{
        "id": c.id, "title": c.title, "turn_count": c.turn_count,
        "updated_at": c.updated_at.strftime("%m-%d %H:%M"),
    } for c in rows])


@router.get("/conversations/{conversation_id}", response_model=R[ConversationDetailData])
async def conversation_detail(conversation_id: int, lu: LoginUser = Depends(get_login_user)):
    """会话详情：问答轮（含来源/相关推荐/阶段/工具，与首次对话展示一致）+ 流程卡片（原始表单还原）。

    展示规则：对话流只呈现问答与流程卡片——流程交互登记在流程表；
    转人工走独立接口（仅入轮次审计，不进对话展示）。
    """
    conv = await Conversation.filter(id=conversation_id, user_id=lu.user_id).first()
    if not conv:
        raise BizError("会话不存在", 404)

    turns = await Turn.filter(conversation_id=conversation_id).exclude(
        intent="handoff").order_by("id")
    stages_map: dict[int, list[dict]] = {}
    if turns:
        rows = await TurnStage.filter(turn_id__in=[t.id for t in turns]).order_by("stage_no")
        for r in rows:
            stages_map.setdefault(r.turn_id, []).append(r)

    turn_items = []
    fb_map = {}
    if turns:
        for fb in await TurnFeedback.filter(turn_id__in=[t.id for t in turns]):
            fb_map[fb.turn_id] = {"rating": fb.rating, "comment": fb.comment}
    for t in turns:
        display = {}
        if t.display_snapshot:
            with contextlib.suppress(json.JSONDecodeError):
                display = json.loads(t.display_snapshot)
        stages, tools = [], []
        for r in stages_map.get(t.id, []):
            try:
                out = json.loads(r.output_data or "{}")
            except json.JSONDecodeError:
                out = {}
            if r.stage_type == "tool":
                stages.append({"stage_type": "tool", "name": r.name, "status": r.status,
                               "summary": out})
                if r.name.startswith("工具调用:"):
                    tools.append({"name": r.name.split(":", 1)[1],
                                  "arguments": (json.loads(r.input_data or "{}").get("arguments") or {}),
                                  "result": out.get("result", "")[:600]})
            else:
                summary = out
                stages.append({"stage_type": r.stage_type, "name": r.name,
                               "status": r.status, "summary": summary})
        turn_items.append({
            "id": t.id, "question": t.question, "answer": t.answer,
            "intent": t.intent, "status": t.status,
            "feedback": fb_map.get(t.id),
            "sources": display.get("sources", []),
            "questions": display.get("questions", []),
            "recommend_flows": display.get("flows", []),
            "stages": stages, "tools": tools,
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # 流程卡片：按实例还原"原始表单"（sections）
    from app.api.flow import build_flow_display
    from app.models import FlowInstance
    flows = []
    for inst in await FlowInstance.filter(conversation_id=conversation_id).order_by("id"):
        fd = await inst.flow_def
        flows.append(build_flow_display(fd, inst))

    return ok({"id": conv.id, "title": conv.title, "turns": turn_items, "flows": flows})


@router.delete("/conversations/{conversation_id}", response_model=R[None])
async def delete_conversation(conversation_id: int, lu: LoginUser = Depends(get_login_user)):
    conv = await Conversation.filter(id=conversation_id, user_id=lu.user_id).first()
    if not conv:
        raise BizError("会话不存在", 404)
    await Turn.filter(conversation_id=conversation_id).delete()
    await Conversation.filter(id=conversation_id).delete()
    return ok(msg="已删除")
