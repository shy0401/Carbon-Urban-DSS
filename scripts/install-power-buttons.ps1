# 바탕화면에 [Carbon DSS 켜기]·[Carbon DSS 끄기] 버튼(.cmd)을 만듭니다. 두 버튼은 scripts\dss-power.ps1 -Mode On/Off를 부릅니다.
#   powershell -ExecutionPolicy Bypass -File scripts\install-power-buttons.ps1
# 저장소 위치를 옮겼으면 다시 실행합니다. 기존 [Carbon Urban DSS 서버 실행](install-desktop-launcher.ps1)은 그대로 둡니다.
$ErrorActionPreference = 'Stop'
$power = Join-Path $PSScriptRoot 'dss-power.ps1'
if (-not (Test-Path -LiteralPath $power)) { throw "missing $power" }
$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($b in @(@('Carbon DSS 켜기.cmd', 'On'), @('Carbon DSS 끄기.cmd', 'Off'))) {
    $content = "@echo off`r`nchcp 65001 >nul`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$power`" -Mode $($b[1])`r`n"
    $path = Join-Path $desktop $b[0]
    [IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Output "button: $path"
}
