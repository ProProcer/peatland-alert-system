# Register the user-authorized service to start after Windows login.
param([int]$Port = 8001)
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install e_platform/requirements-live.txt in .venv first.' }
$windowlessPython = Join-Path $projectRoot '.venv/Scripts/pythonw.exe'
if (Test-Path -LiteralPath $windowlessPython) { $pythonPath = $windowlessPython }
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "-m e_platform.live_service --port $Port" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'PeatlandLiveDashboard' -Action $action -Trigger $trigger -Settings $settings -Description 'Hourly weather/FIRMS refresh, model inference, simulated dispatch and dashboard.' -Force
