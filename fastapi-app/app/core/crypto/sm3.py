# -*- coding: utf-8 -*-
"""SM3 国密摘要算法（纯 Python 实现，零依赖）。

与 Java 侧 com.tienon.common.utils.sm3.SM3Digest 输出逐字节一致，
用于登录口令哈希（见 password.py）。
"""
from __future__ import annotations

_IV = [
    0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
    0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
]


def _rotl(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _t(j: int) -> int:
    return 0x79CC4519 if j < 16 else 0x7A879D8A


def _ff(j: int, x: int, y: int, z: int) -> int:
    if j < 16:
        return x ^ y ^ z
    return (x & y) | (x & z) | (y & z)


def _gg(j: int, x: int, y: int, z: int) -> int:
    if j < 16:
        return x ^ y ^ z
    return (x & y) | ((~x & 0xFFFFFFFF) & z)


def _p0(x: int) -> int:
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x: int) -> int:
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _cf(v: list[int], b: list[int]) -> list[int]:
    w = b[:]
    for j in range(16, 68):
        w.append(_p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15))
                 ^ _rotl(w[j - 13], 7) ^ w[j - 6])
    w1 = [w[j] ^ w[j + 4] for j in range(64)]

    a, bb, c, d, e, f, g, h = v
    for j in range(64):
        ss1 = _rotl((_rotl(a, 12) + e + _rotl(_t(j), j % 32)) & 0xFFFFFFFF, 7)
        ss2 = ss1 ^ _rotl(a, 12)
        tt1 = (_ff(j, a, bb, c) + d + ss2 + w1[j]) & 0xFFFFFFFF
        tt2 = (_gg(j, e, f, g) + h + ss1 + w[j]) & 0xFFFFFFFF
        d = c
        c = _rotl(bb, 9)
        bb = a
        a = tt1
        h = g
        g = _rotl(f, 19)
        f = e
        e = _p0(tt2)
    return [v[i] ^ x for i, x in enumerate([a, bb, c, d, e, f, g, h])]


def sm3_digest(data: bytes) -> bytes:
    """返回 32 字节摘要。标准向量: sm3(b"abc") == 66c7f0f4...8f4ba8e0"""
    pad_len = (56 - (len(data) + 1) % 64) % 64
    padded = data + b"\x80" + b"\x00" * pad_len + (len(data) * 8).to_bytes(8, "big")

    v = _IV[:]
    for i in range(0, len(padded), 64):
        block = [int.from_bytes(padded[i + 4 * k: i + 4 * k + 4], "big") for k in range(16)]
        v = _cf(v, block)
    return b"".join(x.to_bytes(4, "big") for x in v)


def sm3_hex(text: str) -> str:
    """SM3 摘要的小写十六进制串——前端登录时传输的口令形态（对齐原前端协议）。"""
    return sm3_digest(text.encode("utf-8")).hex()
