@echo off
title AI 智能客服 - 一键启动
echo [ALL] 1/4 Elasticsearch...
call "%~dp0start-es.bat"
echo [ALL] 2/4 后端 / 3/4 检索服务 / 4/4 前端（各开独立窗口）...
start "AI-Backend-9310" cmd /c "%~dp0start-backend.bat"
start "AI-Search-8888" cmd /c "%~dp0start-search.bat"
start "AI-Frontend-5173" cmd /c "%~dp0start-frontend.bat"
echo [ALL] 全部启动命令已发出（后端就绪约需 10-20 秒）
pause
