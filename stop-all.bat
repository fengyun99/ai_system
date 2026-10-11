@echo off
title AI 智能客服 - 一键停止
for %%P in (9310 8888 5173 9200 9300) do (
    for /f "tokens=5" %%I in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        echo [停止] 端口 %%P 进程 PID %%I
        taskkill /F /PID %%I >nul 2>&1
    )
)
echo [停止] 完成（ES 为手动实例一并结束；MySQL/Redis 系统服务未动）
pause
