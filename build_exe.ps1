# -*- coding: utf-8 -*-
<#
    STEP 7 AI Agent 一键打包脚本
    产物：dist\Step7AIAgent.exe（单文件，拷贝到其他 Windows 电脑双击即可用）

    用法：在项目根目录右键“使用 PowerShell 运行”，或执行：
          powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#>

$ErrorActionPreference = "Stop"

# Python 解释器路径（本机使用 3.11.9；换电脑时按需修改为 py -3 的路径）
$Python = "C:\Users\16650\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python).Source
}

Write-Host "使用解释器: $Python" -ForegroundColor Cyan

& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name "Step7AIAgent" `
    --collect-submodules snap7 `
    main.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n打包成功：$PSScriptRoot\dist\Step7AIAgent.exe" -ForegroundColor Green
    Write-Host "分发时请把 exe 单独拷贝（首次运行会在同目录自动生成 config.json）。" -ForegroundColor Green
} else {
    Write-Host "`n打包失败，请检查上方错误信息。" -ForegroundColor Red
}
