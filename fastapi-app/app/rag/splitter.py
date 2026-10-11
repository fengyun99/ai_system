# -*- coding: utf-8 -*-
"""递归分块：文档按分隔符层级切分，带重叠；问答对单块。"""
from __future__ import annotations

CHUNK_SIZE = 400      # 字符
CHUNK_OVERLAP = 50

_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " "]


def _split_text(text: str, separators: list[str]) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text.strip()] if text.strip() else []
    sep = separators[0] if separators else ""
    rest = separators[1:]
    parts = text.split(sep) if sep else list(text)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        candidate = (buf + sep + part) if buf else part
        if len(candidate) > CHUNK_SIZE and buf:
            chunks.append(buf.strip())
            # 重叠：保留尾部
            buf = buf[-CHUNK_OVERLAP:] + sep + part if sep else part
        else:
            buf = candidate
    if buf.strip():
        chunks.append(buf.strip())
    # 超长单片继续降级切分
    final: list[str] = []
    for c in chunks:
        if len(c) > CHUNK_SIZE * 1.5 and rest:
            final.extend(_split_text(c, rest))
        else:
            final.append(c)
    return final


def chunk_document(content: str) -> list[str]:
    return _split_text(content, _SEPARATORS)


def chunk_qa(question: str, answer: str) -> list[str]:
    """问答对：问+答合成单块（问在前提高关键词命中）。"""
    text = f"问：{question.strip()}\n答：{answer.strip()}"
    return [text] if text.strip() else []
