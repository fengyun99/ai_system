# -*- coding: utf-8 -*-
"""接口响应契约（response_model 全量声明）。

与前端 web/src/types/api.ts 一一镜像——两端改动必须同步：
  后端：本文件改模型 + 路由挂/改 response_model；
  前端：types/api.ts 改同名 interface（字段名/可空性一致）。
动态载荷（展示快照 sources、阶段 input/output、MCP result、流程卡片 card/
sections 等）显式标 Any——结构由产生方决定、事后原样回放，不做二次消费。

extra=forbid：处理器多吐一个未声明字段 → 响应校验失败（500），逼着改契约，
杜绝"后端悄悄加字段、前端类型装看不见"的漂移。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class _M(BaseModel):
    """契约基类：禁额外字段（响应侧强制）。"""

    model_config = ConfigDict(extra="forbid")


class HealthData(_M):
    service: str


# ============================== auth ==============================

class LoginData(_M):
    token: str


class InfoUser(_M):
    user_id: int
    user_name: str
    nick_name: str
    dept_id: int
    dept_no: str
    dept_name: str
    id_card_masked: str
    phone_masked: str
    identity_bound: bool


class InfoData(_M):
    user: InfoUser
    roles: list[str]
    role_names: list[str]
    permissions: list[str]
    data_scope: int


class RouterNode(_M):
    menu_id: int
    menu_name: str
    path: str
    component: str
    icon: str
    sort: int
    menu_type: str
    perms: str
    children: list["RouterNode"] = []


# ============================== system ==============================

class DeptRow(_M):
    id: int
    dept_no: str
    dept_name: str
    parent_id: int
    ancestors: str
    status: str


class UserRoleBrief(_M):
    id: int
    role_name: str


class UserRow(_M):
    user_id: int
    user_name: str
    nick_name: str
    phone: str
    status: str
    last_login_at: Optional[str] = None
    created_at: str
    dept_no: str
    dept_name: str
    roles: list[UserRoleBrief]


class RoleRow(_M):
    id: int
    role_name: str
    role_key: str
    data_scope: int
    status: str
    remark: str
    menu_ids: list[int]


class MenuRow(_M):
    id: int
    menu_name: str
    parent_id: int
    path: str
    component: str
    perms: str
    menu_type: str
    icon: str
    sort: int
    visible: int


class IdData(_M):
    id: int


# ============================== audit ==============================

class DeptOption(_M):
    dept_no: str
    dept_name: str


class TurnRow(_M):
    id: int
    conversation_id: int
    user: str
    dept_no: str
    question: str
    intent: str
    intent_label: str
    region: str
    theme: str
    theme_label: str
    source_type: str
    status: str
    status_label: str
    tokens_in: int
    tokens_out: int
    ttft_ms: int
    total_ms: int
    trace_id: str
    cost: float
    created_at: str


class TurnPage(_M):
    total: int
    rows: list[TurnRow]


class StageRow(_M):
    stage_no: int
    stage_type: str
    name: str
    input: Any
    output: Any
    status: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_estimated: int
    cost: float
    duration_ms: int
    started_at: str
    finished_at: str
    error_detail: str


class TurnDetailData(_M):
    id: int
    conversation_id: int
    question: str
    answer: str
    intent: str
    intent_label: str
    region: str
    theme: str
    theme_label: str
    snapshot_id: str
    status: str
    tokens_in: int
    tokens_out: int
    ttft_ms: int
    total_ms: int
    source_type: str
    trace_id: str
    cost: float
    error_detail: str
    created_at: str
    stages: list[StageRow]


class LabelCount(_M):
    code: str
    label: str
    count: int


class DashboardData(_M):
    conversation_count: int
    turn_count: int
    done_count: int
    tokens_in: int
    tokens_out: int
    avg_ttft_ms: int
    avg_total_ms: int
    cost_today: float
    cost_total: float
    ingest_cost_today: float
    ingest_cost_total: float
    intent_dist: list[LabelCount]
    theme_dist: list[LabelCount]
    daily: dict[str, int]


class IngestLogRow(_M):
    id: int
    knowledge_id: int
    title: str
    dept_no: str
    chunk_count: int
    tokens_in: int
    tokens_out: int
    tokens_estimated: int
    cost: float
    duration_ms: int
    status: str
    error: str
    operator_user_id: int
    created_at: str


# ============================== knowledge ==============================

class KnowledgeRow(_M):
    id: int
    dept_no: str
    biz_type: str
    title: str
    question: str
    theme: str
    is_public: int
    sync_status: int
    sync_error: str
    created_at: str


class KnowledgePage(_M):
    total: int
    rows: list[KnowledgeRow]


class KnowledgeSaveData(_M):
    id: int
    sync_status: int
    sync_error: str


class SyncOneData(_M):
    chunks: int


class SyncAllData(_M):
    ok: int
    fail: int


class ReconcileData(_M):
    pushed: int
    dropped: int


# ============================== tools ==============================

class ToolRow(_M):
    id: int
    dept_no: str
    name: str
    description: str
    parameters: str          # JSON Schema 字符串（前端按需 parse）
    shared: int
    status: int


# ============================== flow（门户侧） ==============================

class FlowSummary(_M):
    flow_key: str
    name: str
    description: str
    dept_no: str
    mode: str
    url: str


class FlowCurrentData(_M):
    running: bool
    instance_id: Optional[int] = None
    flow_key: Optional[str] = None
    flow_name: Optional[str] = None
    card: Optional[Any] = None   # 交互卡片（form/upload/confirm，动态结构）


class UploadData(_M):
    slot: str
    filename: str
    size: int


# ============================== flow-admin ==============================

class ActionOption(_M):
    key: str
    doc: str


class FlowAdminMeta(_M):
    node_types: list[str]
    actions: list[ActionOption]
    validate_rules: list[str]
    field_types: list[str]
    upload_exts: list[str]


class FlowDefRow(_M):
    id: int
    flow_key: str
    name: str
    description: str
    dept_no: str
    keywords: str
    mode: str
    url: str
    status: int
    published: bool
    dirty: bool
    draft_nodes: int
    published_nodes: int
    draft_invalid: bool


class FlowCreateData(_M):
    id: int
    published: bool


class FlowSaveData(_M):
    id: int
    dirty: bool


class FlowPublishData(_M):
    published_nodes: int


class FlowDefDetail(_M):
    id: int
    flow_key: str
    name: str
    description: str
    dept_no: str
    keywords: str
    mode: str
    url: str
    status: int
    nodes: str                   # 草稿 JSON 字符串
    published_nodes: str


class InstanceRow(_M):
    id: int
    flow_key: str
    flow_name: str
    user: str
    dept_no: str
    dept_name: str
    status: str
    status_label: str
    current: str
    steps: int
    receipt_no: str
    created_at: str
    finished_at: str


class InstancePage(_M):
    total: int
    rows: list[InstanceRow]


class FlowDisplay(_M):
    """流程展示载荷（历史还原/实时共用）；sections 为动态表单形态。"""

    model_config = ConfigDict(extra="ignore")   # 展示快照含扩展段，容忍

    instance_id: int
    flow_key: str
    flow_name: str
    status: str
    steps_count: int
    sections: list[Any]
    created_at: str


class InstanceDetail(_M):
    id: int
    status: str
    steps: list[Any]             # 步进历史（node_key/result 摘要行）
    display: FlowDisplay
    vars_public: dict[str, Any]


class InstanceCancelData(_M):
    status: str


# ============================== rag-audit ==============================

class LabelOption(_M):
    code: str
    label: str


class RagTurnRow(_M):
    id: int
    user: str
    dept_no: str
    question: str
    intent: str
    intent_label: str
    theme: str
    theme_label: str
    status: str
    rag_flag: str
    rag_flag_label: str
    rag_note: str
    rag_flag_by: int
    rag_flag_by_name: str
    rag_flag_at: str
    fb_rating: str
    fb_comment: str
    fb_at: str
    recall_count: int
    kept_count: int
    created_at: str


class RagTurnPage(_M):
    total: int
    rows: list[RagTurnRow]


class FeedbackBrief(_M):
    rating: str
    comment: str
    at: str


class RecallRow(_M):
    fused_rank: int
    knowledge_id: int
    title: str
    fused_score: float
    kept: int


class RagTurnDetailData(_M):
    id: int
    question: str
    answer: str
    intent: str
    intent_label: str
    theme: str
    theme_label: str
    region: str
    dept_no: str
    source_type: str
    status: str
    rag_flag: str
    rag_note: str
    rag_flag_by: int
    rag_flag_at: str
    feedback: Optional[FeedbackBrief] = None
    sources: list[Any]           # 展示快照来源（切块级材料）
    recalls: list[RecallRow]
    created_at: str


class FlagData(_M):
    rag_flag: str
    rag_flag_label: str


class KnowledgeReportRow(_M):
    id: int
    title: str
    dept_no: str
    dept_name: str
    biz_type: str
    biz_type_label: str
    theme: str
    theme_label: str
    sync_status: int
    recall_turns: int
    avg_rank: Optional[float] = None
    avg_score: Optional[float] = None
    kept_count: int
    kept_rate: Optional[float] = None
    flagged_count: int
    user_down: int
    flag_rate: Optional[float] = None
    last_recalled_at: str


class KnowledgeReportSummary(_M):
    kb_total: int
    recalled: int
    never_recalled: int
    flagged_linked: int


class KnowledgeReportPage(_M):
    total: int
    summary: KnowledgeReportSummary
    rows: list[KnowledgeReportRow]


# ============================== chat ==============================

class ChatProgressData(_M):
    running: bool
    status: str


class StopData(_M):
    accepted: bool


class FeedbackData(_M):
    turn_id: int
    rating: str
    comment: str


class HandoffData(_M):
    text: str


class ConversationItem(_M):
    id: int
    title: str
    turn_count: int
    updated_at: str


class FeedbackMini(_M):
    rating: str
    comment: str


class HistoryStage(_M):
    stage_type: str
    name: str
    status: str
    summary: Any


class HistoryTool(_M):
    name: str
    arguments: Any
    result: str


class HistoryTurn(_M):
    id: int
    question: str
    answer: str
    intent: str
    status: str
    feedback: Optional[FeedbackMini] = None
    sources: list[Any]
    questions: list[Any]
    recommend_flows: list[Any]
    stages: list[HistoryStage]
    tools: list[HistoryTool]
    created_at: str


class ConversationDetailData(_M):
    id: int
    title: str
    turns: list[HistoryTurn]
    flows: list[FlowDisplay]


# ============================== open ==============================

class OpenSource(_M):
    title: str
    dept_no: str
    public: bool
    score: Optional[float] = None


class OpenAskData(_M):
    conversation_id: int
    turn_id: int
    trace_id: str
    answer: str
    sources: list[OpenSource]
    questions: list[Any]
    error: Optional[str] = None


class OpenAccountData(_M):
    action: str
    id_card: str                # 已脱敏
    result: str                 # MCP 工具返回的格式化文本（balance/loan/deposit）


class OpenKnowledgeRow(_M):
    id: int
    dept_no: str
    biz_type: str
    title: str
    question: str
    theme: str


class OpenKnowledgePage(_M):
    total: int
    rows: list[OpenKnowledgeRow]


class OpenTurnRow(_M):
    id: int
    conversation_id: int
    question: str
    intent: str
    region: str
    theme: str
    status: str
    trace_id: str
    source_system: str
    tokens_in: int
    tokens_out: int
    total_ms: int
    created_at: str


class OpenTurnPage(_M):
    total: int
    rows: list[OpenTurnRow]
