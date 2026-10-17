param([int]$Port = 8001, [int]$IntervalSeconds = 3600, [switch]$Background)
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the live environment first: uv venv --python 3.12 .venv; uv pip install --python .venv/Scripts/python.exe -r e_platform/requirements-live.txt'
}
$liveArguments = @('-m', 'e_platform.live_service', '--port', "$Port", '--interval-seconds', "$IntervalSeconds")
if ($Background) {
    $runtimePath = Join-Path $projectRoot 'data/runtime/live'
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    $process = Start-Process -FilePath $pythonPath -ArgumentList $liveArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'service.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'service.stderr.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $runtimePath 'service.pid')
    Write-Output "Live service started (PID $($process.Id)); http://127.0.0.1:$Port"
} else {
    Push-Location -LiteralPath $projectRoot
    try { & $pythonPath @liveArguments } finally { Pop-Location }
}
