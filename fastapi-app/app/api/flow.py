# -*- coding: utf-8 -*-
"""业务流程路由：办理启动/节点提交/取消（SSE）+ 状态恢复 + 可用流程清单。

流程交互同样登记进审计流水：一次交互 = 一轮 turn（intent='flow'），
阶段行记录节点步进（stage_type='flow'）与自动节点执行的工具调用（stage_type='tool'）。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.common.deps import LoginUser, get_login_user
from app.common.response import BizError, ok, R
from app.api.schemas import FlowCurrentData, FlowSummary, UploadData
from app.flow_engine import cancel_flow, current_state, start_flow, submit_node
from app.models import Conversation, FlowDef, FlowInstance

router = APIRouter(prefix="/flow", tags=["flow"])


def _sse_line(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


async def _stream(flow_def: FlowDef, instance, t0: float, events: list[dict]) -> AsyncIterator[str]:
    """流程交互只登记到流程表（flow_instance.steps），不写对话轮次——
    对话展示层只呈现卡片表单，避免 [流程提交]/文字说明等无关内容进入对话框。"""
    for ev in events:
        yield _sse_line(ev)
    done_ev: dict = {"type": "done", "instance_id": instance.id}
    # 仅当流程结束（完成/取消）才下发"最后一态表单"；办理中保持交互卡片
    if instance.status != "running":
        done_ev["flow_display"] = build_flow_display(flow_def, instance)
    yield _sse_line(done_ev)
    await asyncio.sleep(0)


def build_flow_display(flow_def: FlowDef, instance) -> dict:
    """流程的展示载荷：原始表单形态 sections（前端历史/实时共用）。"""
    from app.rag.graph import flow_sections
    try:
        steps = json.loads(instance.steps or "[]")
    except (json.JSONDecodeError, TypeError):
        steps = []
    return {
        "instance_id": instance.id, "flow_key": flow_def.flow_key, "flow_name": flow_def.name,
        "status": instance.status, "steps_count": len(steps),
        "sections": flow_sections(flow_def, instance),
        "created_at": instance.created_at.strftime("%Y-%m-%d %H:%M:%S") if instance.created_at else "",
    }


async def _ensure_conv(conversation_id: int | None, lu: LoginUser, title: str) -> Conversation:
    if conversation_id:
        conv = await Conversation.filter(id=conversation_id, user_id=lu.user_id).first()
        if not conv:
            raise BizError("会话不存在", 404)
        return conv
    return await Conversation.create(user_id=lu.user_id, dept_no=lu.dept_no, title=title)


@router.get("/list", response_model=R[list[FlowSummary]])
async def list_flows(lu: LoginUser = Depends(get_login_user)):
    rows = await FlowDef.filter(status=1)
    return ok([{
        "flow_key": f.flow_key, "name": f.name, "description": f.description,
        "dept_no": f.dept_no, "mode": f.mode or "embed", "url": f.url or "",
    } for f in rows if f.dept_no in (lu.dept_no, "35000")])


@router.get("/current", response_model=R[FlowCurrentData])
async def flow_current(conversation_id: int = Query(...), lu: LoginUser = Depends(get_login_user)):
    return ok(await current_state(conversation_id, lu))


class StartBody(BaseModel):
    flow_key: str
    conversation_id: int | None = None


@router.post("/start")
async def flow_start(body: StartBody, lu: LoginUser = Depends(get_login_user)):
    conv = await _ensure_conv(body.conversation_id, lu, title="业务办理")
    t0 = time.perf_counter()
    result = await start_flow(conv.id, lu, body.flow_key)
    flow_def, instance = result["flow_def"], result["instance"]
    events = [
        {"type": "meta", "conversation_id": conv.id, "title": conv.title, "turn_id": None},
        {"type": "flow_start", "instance_id": instance.id, "flow_key": flow_def.flow_key,
         "flow_name": flow_def.name, "card": result.get("card")},
        *(result.get("auto_events") or []),
    ]
    return StreamingResponse(
        _stream(flow_def, instance, t0, events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class SubmitBody(BaseModel):
    instance_id: int
    node_key: str
    data: dict = {}


@router.post("/submit")
async def flow_submit(body: SubmitBody, lu: LoginUser = Depends(get_login_user)):
    """提交流程节点：校验失败 → form_error 事件（停留原节点）；成功 → 下一卡片/完成事件。

    注：流程交互**只登记在流程表**（flow_instance.steps），不产生对话轮次。
    """
    t0 = time.perf_counter()
    result = await submit_node(body.instance_id, lu, body.node_key, body.data)
    instance, flow_def = result["instance"], result["flow_def"]
    conv = await instance.conversation

    events = [{"type": "meta", "conversation_id": conv.id, "title": conv.title,
               "turn_id": None, "instance_id": instance.id}]
    if not result.get("ok", True):
        events.append({"type": "form_error", "instance_id": instance.id,
                       "node_key": result["node"]["key"], "errors": result["errors"]})
        return StreamingResponse(
            _stream(flow_def, instance, t0, events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    for ev in result["events"]:
        events.append(ev)
    if not result["done"] and result.get("card"):
        events.append({"type": "card", "card": result["card"]})
    return StreamingResponse(
        _stream(flow_def, instance, t0, events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "flow"
_UPLOAD_MAX = 10 * 1024 * 1024
_UPLOAD_EXTS = {".jpg", ".jpeg", ".png", ".pdf"}


@router.post("/upload/{instance_id}", response_model=R[UploadData])
async def flow_upload(instance_id: int, slot: str = Form(...), file: UploadFile = File(...),
                      lu: LoginUser = Depends(get_login_user)):
    """材料上传（对接演示）：存本地 uploads/flow/{instance}/，登记到流程变量。

    扩展名白名单 jpg/jpeg/png/pdf，单文件 ≤10MB；仅办理中本人实例可传。
    """
    instance = await FlowInstance.get_or_none(id=instance_id)
    if not instance or instance.user_id != lu.user_id:
        raise BizError("流程实例不存在", 404)
    if instance.status != "running":
        raise BizError("流程已结束，不能上传材料", 409)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _UPLOAD_EXTS:
        raise BizError(f"不支持的文件类型 {ext or '(无后缀)'}（允许：jpg/png/pdf）", 422)
    payload = await file.read()
    if len(payload) > _UPLOAD_MAX:
        raise BizError("文件超过 10MB 上限", 422)
    safe = re.sub(r"[^\w一-龥.-]", "_", Path(file.filename or "file").stem)[:60] + ext
    target = _UPLOAD_DIR / str(instance_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / safe).write_bytes(payload)
    # 登记到流程变量（槽位 → 文件信息；submit upload 节点时固化为 files）
    vars_ = json.loads(instance.vars or "{}")
    vars_.setdefault("uploaded", {})[slot] = {
        "filename": safe, "size": len(payload),
        "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    instance.vars = json.dumps(vars_, ensure_ascii=False)
    await instance.save(update_fields=["vars"])
    return ok({"slot": slot, "filename": safe, "size": len(payload)})


class CancelBody(BaseModel):
    instance_id: int


@router.post("/cancel")
async def flow_cancel(body: CancelBody, lu: LoginUser = Depends(get_login_user)):
    t0 = time.perf_counter()
    result = await cancel_flow(body.instance_id, lu)
    instance, flow_def = result["instance"], result["flow_def"]
    conv = await instance.conversation
    events = [{"type": "meta", "conversation_id": conv.id, "title": conv.title, "turn_id": None},
              *result["events"]]
    return StreamingResponse(
        _stream(flow_def, instance, t0, events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
