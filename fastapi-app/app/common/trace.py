# -*- coding: utf-8 -*-
"""溯源 TraceId：门户与开放接口共用的生成与透传规则。"""
from __future__ import annotations

import uuid

from fastapi import Request


def trace_id_of(request: Request) -> str:
    """优先透传调用方 X-Trace-Id（去空白、截断 64），缺省系统生成 uuid hex。"""
    return (request.headers.get("X-Trace-Id") or "").strip()[:64] or uuid.uuid4().hex
