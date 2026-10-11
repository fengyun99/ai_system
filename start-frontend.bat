@echo off
title AI 智能客服 - 前端 (5173)
cd /d "%~dp0web"
if not exist node_modules (
    echo [提示] 首次运行，安装依赖...
    call npm install
)
echo [前端] 启动 Vite (http://127.0.0.1:5173) ...
call npm run dev
pause
