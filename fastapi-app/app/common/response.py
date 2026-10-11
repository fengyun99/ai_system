# -*- coding: utf-8 -*-
"""统一响应封装——对齐原 Java AjaxResult 形态 {code, msg, data}。

R[T] 是该形态的 Pydantic 契约（路由 response_model 用）：后端发出的响应
必须能装进已声明的 data 结构，多一个字段即拒发（extra=forbid），
前端 TS 类型按同一契约镜像（web/src/types/api.ts），两端同源。
"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class R(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    code: int
    msg: str
    data: Optional[T] = None


def ok(data: Any = None, msg: str = "操作成功") -> dict:
    return {"code": 200, "msg": msg, "data": data}


def fail(msg: str = "操作失败", code: int = 500) -> dict:
    return {"code": code, "msg": msg, "data": None}


class BizError(Exception):
    """业务异常：message 透出给前端，code 映射 HTTP 语义。"""

    def __init__(self, msg: str, code: int = 400):
        self.msg = msg
        self.code = code
        super().__init__(msg)
