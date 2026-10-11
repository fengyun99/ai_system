@echo off
title AI 智能客服 - 联网检索服务 (8888)
cd /d "%~dp0fastapi-app"
if not exist .venv\Scripts\python.exe (
    echo [错误] 未找到 .venv，请先在后端目录执行 uv sync
    pause
    exit /b 1
)
echo [检索] 启动自建联网检索服务 (SearXNG 协议兼容, 127.0.0.1:8888) ...
.venv\Scripts\python.exe -m uvicorn search_service.main:app --host 127.0.0.1 --port 8888
pause
