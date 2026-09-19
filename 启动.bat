@echo off
rem ============================================================
rem  STEP 7 AI Agent 一键启动（使用项目内置 Python 运行时）
rem  无需在本机安装任何 Python 环境
rem ============================================================
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1

if not exist "runtime\pythonw.exe" (
    echo [错误] 未找到 runtime\pythonw.exe，请确认 runtime 目录完整。
    echo 若首次解压项目，请先阅读 使用文档.md 第 2 节。
    pause
    exit /b 1
)

rem 以无控制台窗口方式启动主程序
start "" "runtime\pythonw.exe" main.py
endlocal
