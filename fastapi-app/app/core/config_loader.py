# -*- coding: utf-8 -*-
"""统一配置加载器——对齐原 Java DecryptConfig 机制。

规则（与 Java 侧 project-extend DecryptConfig 一致）：
  1. 配置文件（config/app.yml）中以 Enc[...] 包裹的值 = SM4-CTR 密文，
     启动加载时解密为明文供运行时使用；
  2. 密钥缺省与 Java 相同（Q1w2e3r4t5y6u7i8），可用 decrypt.key 覆盖；
  3. 明文升级：标记为敏感的字段若以明文填写，首次启动自动加密为 Enc[...]
     并回写配置文件（幂等，二次启动不再改写），与 Java 侧"自动加密"行为对齐。

CLI：
  python -m app.core.config_cli <明文>        # 输出 Enc[...] 供粘贴
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .crypto import decrypt_enc_value
from .crypto.sm4 import sm4_ctr

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_KEY = "Q1w2e3r4t5y6u7i8"  # 与 Java SM4Utils.DEFAULT_KEY 一致

_ENC_RE = re.compile(r"^Enc\[(.+)\]$")

# 敏感字段路径（点分）：这些位置出现明文时自动加密回写
SENSITIVE_PATHS = (
    "mysql.password", "es.password", "redis.password", "jwt.secret",
)


def encrypt_to_enc(plaintext: str, key: str = DEFAULT_KEY) -> str:
    """明文 → Enc[base64(SM4-CTR)]（Java 同款算法/密钥/零IV）。"""
    cipher = sm4_ctr(plaintext.encode("utf-8"), key.encode("utf-8"))
    return f"Enc[{base64.b64encode(cipher).decode('ascii')}]"


def _resolve(path: str, tree: dict) -> tuple[bool, Any]:
    node: Any = tree
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _assign(path: str, value: Any, tree: dict) -> None:
    parts = path.split(".")
    node = tree
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _decrypt_value(value: Any, key: str) -> Any:
    if isinstance(value, str):
        m = _ENC_RE.match(value.strip())
        if m:
            return decrypt_enc_value(m.group(1), key)
    return value


def _walk_decrypt(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        return {k: _walk_decrypt(v, key) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk_decrypt(v, key) for v in node]
    return _decrypt_value(node, key)


class AppConfig:
    """加载 config/app.yml：解密 Enc[...]，敏感明文自动加密回写。

    未显式指定文件名时尊重环境变量 AI_APP_CONFIG（Docker 用 app.docker.yml）。
    """

    def __init__(self, filename: str | None = None, key: str | None = None):
        import os
        self.path = CONFIG_DIR / (filename or os.environ.get("AI_APP_CONFIG", "app.yml"))
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self._key = ((raw.get("decrypt") or {}).get("key")) or key or DEFAULT_KEY

        # 全树解密（任何位置的 Enc[...] 都会被解开）
        decrypted = _walk_decrypt(raw, self._key)

        # 敏感字段明文升级：原始文件中该位置不是 Enc[...] 形态且值非空 → 加密回写
        upgraded = []
        for p in SENSITIVE_PATHS:
            ok, val = _resolve(p, decrypted)
            if not ok or not isinstance(val, str) or not val:
                continue
            ok_raw, raw_val = _resolve(p, raw)
            if ok_raw and isinstance(raw_val, str) and _ENC_RE.match(raw_val.strip()):
                continue
            upgraded.append(p)
        if upgraded:
            self._rewrite_encrypted(raw, decrypted, upgraded)

        self._tree = decrypted

    def _rewrite_encrypted(self, raw: dict, decrypted: dict, upgraded: list) -> None:
        # 以磁盘最新内容为底，只改升级字段，避免覆盖并发修改
        new_tree = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        for p in upgraded:
            ok, val = _resolve(p, decrypted)
            if ok and val:
                _assign(p, encrypt_to_enc(str(val), self._key), new_tree)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".yml.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(new_tree, f, allow_unicode=True, sort_keys=False)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # ---- 访问 ----
    def get(self, path: str, default: Any = None) -> Any:
        ok, val = _resolve(path, self._tree)
        return val if ok else default

    def sub(self, prefix: str) -> dict:
        ok, val = _resolve(prefix, self._tree)
        return dict(val) if ok and isinstance(val, dict) else {}

    @property
    def tree(self) -> dict:
        return self._tree
