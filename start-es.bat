@echo off
title AI 智能客服 - Elasticsearch (9200)
set ES_URL=https://127.0.0.1:9200
set ES_HOME=C:\elasticsearch-8.19.22

rem 幂等：ES 已在 9200 应答则跳过（重复实例会撞数据目录锁 node.lock）
curl -k -s -o NUL --max-time 3 %ES_URL% >nul 2>&1
if %errorlevel%==0 (
    echo [ES] 已在运行: %ES_URL%
    goto done
)

echo [ES] 启动 Elasticsearch（独立窗口，关闭该窗口即停止 ES）...
start "Elasticsearch 8.19" /D "%ES_HOME%\bin" elasticsearch.bat

echo [ES] 等待 %ES_URL% 就绪（冷启动 1-3 分钟属正常）...
set /a tries=0
:waitloop
curl -k -s -o NUL --max-time 3 %ES_URL% >nul 2>&1
if not errorlevel 1 goto ready
set /a tries+=1
<nul set /p "=."
if %tries% geq 90 goto timeoutwarn
ping -n 3 127.0.0.1 >nul
goto waitloop

:ready
echo.
echo [ES] 就绪: %ES_URL%
goto done
:timeoutwarn
echo.
echo [ES] 警告: 180 秒内未就绪，请查看 %ES_HOME%\logs\ 下最新日志
:done
echo.
pause
