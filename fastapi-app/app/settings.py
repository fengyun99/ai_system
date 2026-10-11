# -*- coding: utf-8 -*-
"""运行时配置——全部来自 config/app.yml（Enc[...] 已解密后的明文仅存于内存）。

环境变量 AI_APP_CONFIG 可指定配置文件名（Docker 用 app.docker.yml 切换服务名主机）。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .core.config_loader import AppConfig

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
MODEL_CONFIG_PATH = CONFIG_DIR / "model-config.json"


@lru_cache(maxsize=1)
def get_settings() -> dict:
    cfg = AppConfig(filename=os.environ.get("AI_APP_CONFIG", "app.yml"))
    return {
        "base_dir": BASE_DIR,
        "server": cfg.sub("server"),
        "mysql": cfg.sub("mysql"),
        "es": cfg.sub("es"),
        "redis": cfg.sub("redis"),
        "jwt": cfg.sub("jwt"),
        "rag": cfg.sub("rag"),
        "websearch": cfg.sub("websearch"),
        "mcp": cfg.sub("mcp"),
    }
