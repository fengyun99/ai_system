# -*- coding: utf-8 -*-
"""AI 智能客服系统（Python 版）入口。

启动链（lifespan）：加载配置(Enc 解密) → Tortoise(MySQL) → model-config 加载
→ ES 索引就绪 → MCP session_manager 启动（streamable-http 同进程服务）。
"""
from __future__ import annotations

import importlib
import pkgutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise import Tortoise

from app import api
from app.api.schemas import HealthData
from app.common.response import BizError, R
from app.rag import llm, vectorstore
from app.rag.tools import mcp
from app.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    mysql = settings["mysql"]
    await Tortoise.init(
        db_url=(f"mysql://{mysql['user']}:{mysql['password']}"
                f"@{mysql['host']}:{mysql['port']}/{mysql['database']}"),
        modules={"models": ["app.models"]},
        _enable_global_fallback=True,   # 请求处理器与启动任务不同 contextvar 上下文
    )
    await Tortoise.generate_schemas()          # 演示库自动建表（幂等）
    llm.load_model_config()                    # model-config.json（api_key Enc 自动升级）
    es_cfg = settings["es"]
    # ES 服务为手动启动模式：未启动时自动拉起（自动化测试免人工干预）
    from app.core.ensure_es import ensure_es
    if not await ensure_es(es_cfg["host"], es_cfg["port"]):
        raise RuntimeError(f"Elasticsearch {es_cfg['host']}:{es_cfg['port']} 不可达（自动启动失败）")
    vectorstore.ensure_index()                 # ES 索引与映射就绪
    import jieba  # noqa: F401 预热分词器
    print(f"[startup] ready: db={mysql['database']} es_index={vectorstore.index_name()}")
    # MCP 工具服务会话管理器（streamable_http_app 挂载后须由宿主 lifespan 启动）
    async with mcp.session_manager.run():
        yield
    await Tortoise.close_connections()


def create_app() -> FastAPI:
    app = FastAPI(title="AI 智能客服系统（Python 版）", version="1.0.0", lifespan=lifespan)

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["*"])

    @app.exception_handler(BizError)
    async def biz_error_handler(_: Request, exc: BizError):
        return JSONResponse({"code": exc.code, "msg": exc.msg, "data": None},
                            status_code=200)

    @app.get("/api/health", response_model=R[HealthData])
    async def health():
        return {"code": 200, "msg": "ok", "data": {"service": "ai-system-python"}}

    # API 路由自动扫描注册（app.api 包下全部模块）
    for m in pkgutil.iter_modules(api.__path__):
        module = importlib.import_module(f"app.api.{m.name}")
        if hasattr(module, "router"):
            app.include_router(module.router, prefix="/api")

    # MCP 工具服务：streamable_http_app 内部自带 /mcp 路由，须挂根路径；
    # 且必须在全部 API 路由注册之后（根挂载会吞掉其后注册的一切路径）
    app.mount("/", mcp.streamable_http_app())

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    s = get_settings()["server"]
    uvicorn.run("app.main:app", host=s.get("host", "127.0.0.1"), port=int(s.get("port", 9310)))
