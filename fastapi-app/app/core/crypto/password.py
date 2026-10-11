# -*- coding: utf-8 -*-
"""登录口令协议——逐位复刻原 Java(DefaultPasswordEncoder + Basecrypt) 的国密方案。

原 Java 协议（迁移前后保持一致，数据库中同一账号口令可直接互认）：
  1. 前端不传明文，传输 P = hex(sm3(明文))           （Basecrypt.sm3(String)）
  2. 后端入库/校验值 = "$1a" + hex(sm3(sm3(P + "{" + P + "}")))   （Basecrypt.hash，自加盐双重摘要）
  3. "$1a" 为算法版本号，预留升级空间（Version.$1A）。
"""
from __future__ import annotations

from .sm3 import sm3_digest

VERSION = "$1a"


def hash_password(transport_password: str) -> str:
    """由前端传输形态（SM3 摘要 hex）计算入库密文。

    等价 Java: Version.$1A.version + Basecrypt.hash(pwd)
    """
    data = (transport_password + "{" + transport_password + "}").encode("utf-8")
    return VERSION + sm3_digest(sm3_digest(data)).hex()


def encode_password(plaintext: str) -> str:
    """由明文一步得到入库密文（前端摘要 + 后端双重哈希）。"""
    return hash_password(sm3_plaintext(plaintext))


def sm3_plaintext(plaintext: str) -> str:
    """前端形态：明文的 SM3 摘要 hex。"""
    return sm3_digest(plaintext.encode("utf-8")).hex()


def matches(transport_password: str, encoded_password: str) -> bool:
    """校验前端传输口令与库中密文是否一致（对齐 DefaultPasswordEncoder.matches）。"""
    if not encoded_password or not encoded_password.startswith(VERSION):
        return False
    return encoded_password == hash_password(transport_password)
