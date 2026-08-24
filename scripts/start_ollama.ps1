# 一键启动本地 Ollama 服务（给不想记命令的你）
# 用法：在这个文件上右键 →「使用 PowerShell 运行」；或在终端里执行：
#   powershell -ExecutionPolicy Bypass -File scripts\start_ollama.ps1
#
# 关键：这里写死了模型目录在 E 盘，绝不占 C 盘。
# 提示：跑起来后，这个窗口就是“服务本体”，开着别关；要停服务，关掉窗口即可。

$ErrorActionPreference = "Stop"

$env:OLLAMA_MODELS = "E:\tools\Ollama\models"
$env:OLLAMA_HOST   = "127.0.0.1:11434"
$ollama = "E:\tools\Ollama\ollama.exe"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " 启动本地 Ollama 服务" -ForegroundColor Cyan
Write-Host " 模型目录: $env:OLLAMA_MODELS" -ForegroundColor Cyan
Write-Host " 监听地址: http://$env:OLLAMA_HOST" -ForegroundColor Cyan
Write-Host " （此窗口即服务本体，开着别关；关窗口=停服务）" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Cyan

# 先清掉可能残留的、走 C 盘默认路径的旧进程，避免端口/路径打架
taskkill /F /IM "ollama app.exe" /T 2>$null | Out-Null
taskkill /F /IM "ollama.exe" /T 2>$null | Out-Null
Start-Sleep -Seconds 2

& $ollama serve
