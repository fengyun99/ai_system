@echo off
title AI 智能客服 - 后端 (9310)
cd /d "%~dp0fastapi-app"
if not exist .venv\Scripts\python.exe (
    echo [错误] 未找到 .venv，请先执行: uv sync
    pause
    exit /b 1
)
rem 后端启动时会自动拉起未运行的 ES 服务（需管理员权限）
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 当前非管理员，若 ES 未启动将无法自动拉起，建议右键以管理员身份运行
)
echo [后端] 启动 FastAPI (127.0.0.1:9310, MCP 同进程挂载 /mcp) ...
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 9310
pause
