# 시연 주소 지킴이(scripts\demo-watch.ps1)를 작업 스케줄러에 등록합니다. 관리자 권한은 필요 없습니다.
# Windows에 로그온하면 1분 뒤 시작하고 5분마다 다시 실행합니다. 창은 뜨지 않습니다(wscript로 숨겨 실행).
#   등록:   powershell -ExecutionPolicy Bypass -File scripts\install-demo-watch.ps1
#   지우기: powershell -ExecutionPolicy Bypass -File scripts\install-demo-watch.ps1 -Remove
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$TaskName = 'CarbonDSS demo address watch'
$vbs = Join-Path $PSScriptRoot 'demo-watch.vbs'
$root = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    $old = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($old) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; Write-Output "removed: $TaskName" } else { Write-Output "not registered: $TaskName" }
    exit 0
}
if (-not (Test-Path -LiteralPath $vbs)) { throw "missing $vbs" }

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$every = New-TimeSpan -Minutes 5
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" -Argument ('//B //NoLogo "' + $vbs + '"') -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT1M'
$logon.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $every).Repetition
$now = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval $every
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$description = 'Carbon Urban DSS: Docker와 빠른 터널을 살피고, 시연 주소가 바뀌면 GitHub Pages(https://shy0401.github.io/Carbon-Urban-DSS/)의 demo.json을 고칩니다. scripts\demo-watch.ps1'
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logon, $now) -Settings $settings -Principal $principal -Description $description -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = $task | Get-ScheduledTaskInfo
Write-Output "registered: $($task.TaskPath)$($task.TaskName) state=$($task.State) next=$($info.NextRunTime)"
foreach ($tr in $task.Triggers) {
    $kind = ($tr.CimClass.CimClassName -replace '^MSFT_Task', '' -replace 'Trigger$', '')
    $dur = if ($tr.Repetition.Duration) { $tr.Repetition.Duration } else { 'indefinitely' }
    Write-Output "  trigger $kind delay=$($tr.Delay) every=$($tr.Repetition.Interval) for=$dur"
}
