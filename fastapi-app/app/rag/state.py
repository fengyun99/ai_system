# -*- coding: utf-8 -*-
"""LangGraph Agentic RAG 状态定义（TypedDict）。

一轮回答的完整状态：前置推理（意图/区域/分类/分化）→ 检索/重排 → 生成/工具执行，
每步产出 stage 登记行（stage_rows）与 token 记账（meter），供轮次审计表落库与前端展示。
emit 为 SSE 发射回调（运行时注入，非持久化字段）。
"""
from __future__ import annotations

from typing import Annotated, Callable, TypedDict

from app.rag.llm import TokenMeter


def append_list(old: list | None, new: list | None) -> list:
    """列表追加 reducer：stage_rows / tool_events 等累积字段。"""
    out = list(old or [])
    out.extend(new or [])
    return out


class ChatState(TypedDict, total=False):
    # ---- 输入 ----
    question: str
    history: list[dict]
    user_id: int
    dept_no: str                  # 提问人机构（登记归属）
    dept_name: str
    user_id_card: str             # 登录态身份（mock 三要素之一，查询/注入用，不向用户索要）
    user_name: str
    extra_depts: list[str]        # 祖先链（检索可见性扩展）
    emit: Callable
    meter: TokenMeter
    # ---- 前置推理 ----
    intent: str                   # rag | business | chitchat
    intent_reason: str
    region_name: str
    is_external: bool
    target_dept_no: str           # 区域识别后的检索租户
    theme: str
    sub_queries: list[str]
    # ---- 检索与生成 ----
    materials: list[dict]
    kb_materials: list[dict]       # 知识库召回材料（联网混合展示保留）
    web_materials: list[dict]      # 联网检索材料
    web_ok: bool                   # 联网是否取到材料
    snapshot_id: str
    rerank_used: bool
    sufficient: bool             # 材料充分性判断结果
    web_attempted: bool          # 是否已走联网检索（决定拒答话术）
    answer: str
    refused: bool
    # ---- 召回审计（RAG 审计落库：候选知识清单 + 重排保留集，_persist 写 turn_recall） ----
    recall_audit: list[dict]
    recall_kept: list[str]
    # ---- 登记与事件 ----
    stage_rows: Annotated[list[dict], append_list]
    error: str
