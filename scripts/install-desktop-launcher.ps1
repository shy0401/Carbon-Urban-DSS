$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $env:USERPROFILE 'Desktop\Carbon Urban DSS 서버 실행.cmd'
$content = @"
@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$projectRoot\scripts\launch-prototype.ps1"
if errorlevel 1 pause
"@
[IO.File]::WriteAllText($launcherPath, $content, [Text.UTF8Encoding]::new($false))
Write-Host "바탕화면 실행기 설치 완료: $launcherPath"
