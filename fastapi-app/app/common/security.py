# -*- coding: utf-8 -*-
"""JWT 签发/校验——HS512，密钥与原 Java token.secret 相同（Enc 解密后使用）。

与 Java 差异说明：Java 侧以 JWT→Redis(login_tokens:uuid) 双层校验；
Python 版为演示精简为无状态 JWT（payload 含 user_id/dept_no），Redis 仅承担
停止信号与在线状态。签名语义保持一致。
"""
from __future__ import annotations

import time

import jwt

from app.settings import get_settings

_SECRET: str | None = None


def _secret() -> str:
    global _SECRET
    if _SECRET is None:
        _SECRET = get_settings()["jwt"]["secret"]
    return _SECRET


def create_token(user_id: int, user_name: str, dept_no: str) -> str:
    expire = int(get_settings()["jwt"].get("expire_minutes", 720)) * 60
    payload = {
        "user_id": user_id,
        "user_name": user_name,
        "dept_no": dept_no,
        "exp": int(time.time()) + expire,
    }
    return jwt.encode(payload, _secret(), algorithm="HS512")


def verify_token(token: str) -> dict:
    """校验并返回 payload；失败抛 jwt 异常（调用方转 401）。"""
    return jwt.decode(token, _secret(), algorithms=["HS512"])
