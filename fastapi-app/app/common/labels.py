# -*- coding: utf-8 -*-
"""展示标签单一来源：意图/主题/质检标记的 code→中文映射。

仪表盘、轮次审计、RAG 审计、各类导出共用同一份（API 同时返回 code 与中文，
前端不再各自维护映射表）；新增 code 只改这里。
"""
from __future__ import annotations

INTENT_LABELS: dict[str, str] = {
    "rag": "知识问答",
    "business": "业务办理",
    "chitchat": "寒暄闲聊",
    "off_topic": "无关话题",
    "handoff": "转人工",
    "unknown": "未知",
}

THEME_LABELS: dict[str, str] = {
    "deposit": "缴存",
    "loan": "贷款",
    "withdraw": "提取",
    "other": "其他",
    "unknown": "未知",
}

# RAG 质检标记（Turn.rag_flag 逗号分隔存储；code 互不为子串，支持 contains 过滤）
RAG_FLAG_LABELS: dict[str, str] = {
    "recall_miss": "召回不准",
    "answer_wrong": "答案有误",
    "kb_stale": "知识过旧",
    "flag_other": "其他",
}

STATUS_LABELS: dict[str, str] = {
    "done": "完成",
    "generating": "生成中",
    "interrupted": "已停止",
    "error": "错误",
}

SOURCE_LABELS: dict[str, str] = {
    "portal": "门户",
    "open": "开放接口",
}


def intent_label(code: str | None) -> str:
    code = (code or "").strip() or "unknown"
    return INTENT_LABELS.get(code, code)


def theme_label(code: str | None) -> str:
    code = (code or "").strip() or "unknown"
    return THEME_LABELS.get(code, code)


def rag_flag_label(codes: str | list[str]) -> str:
    if isinstance(codes, str):
        codes = [c for c in codes.split(",") if c]
    return "、".join(RAG_FLAG_LABELS.get(c, c) for c in codes if c)
