# -*- coding: utf-8 -*-
"""票据 03：trace 全入口统一——门户与开放接口共用同一 TraceId 规则。

验收（.scratch/observability/issues/03）：
  - 门户创建轮次时登记 TraceId（请求头携带则透传，否则系统生成），与开放接口共用同一实现
  - 携带自定义 X-Trace-Id 的门户请求，落库轮次与之一致
"""
from __future__ import annotations

import re

from starlette.datastructures import Headers

from app.common.trace import trace_id_of
from app.api.open import _trace_of


def _req(headers: dict | None = None):
    # 用 Starlette Headers 还原真实请求头的大小写不敏感语义
    return type("R", (), {"headers": Headers(headers or {})})()


def test_header_passthrough():
    assert trace_id_of(_req({"X-Trace-Id": "abc-123"})) == "abc-123"


def test_header_case_insensitive():
    assert trace_id_of(_req({"x-trace-id": "lower-1"})) == "lower-1"


def test_strips_whitespace_and_truncates_to_64():
    long_id = "x" * 80
    assert trace_id_of(_req({"X-Trace-Id": f"  {long_id}  "})) == "x" * 64


def test_generated_when_missing_or_blank():
    a = trace_id_of(_req())
    b = trace_id_of(_req({"X-Trace-Id": "   "}))
    for v in (a, b):
        assert re.fullmatch(r"[0-9a-f]{32}", v)
    assert a != b


def test_open_trace_of_still_returns_source_system():
    assert _trace_of(_req({"X-Trace-Id": "t1", "X-Source-System": "crm"})) == ("t1", "crm")
    tid, src = _trace_of(_req({}))
    assert src == ""
    assert re.fullmatch(r"[0-9a-f]{32}", tid)
