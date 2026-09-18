param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Test-DockerEngine {
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

try {
    if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI를 찾을 수 없습니다. Docker Desktop을 먼저 설치하세요.'
    }

    if (!(Test-DockerEngine)) {
        $desktopCandidates = @(
            "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
            "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
        )
        $desktop = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (!$desktop) { throw 'Docker Desktop 실행 파일을 찾을 수 없습니다.' }
        Write-Host 'Docker Desktop을 시작합니다. 엔진 준비에는 잠시 시간이 걸릴 수 있습니다.'
        Start-Process -FilePath $desktop -WindowStyle Hidden
        $ready = $false
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            Start-Sleep -Seconds 2
            if (Test-DockerEngine) { $ready = $true; break }
        }
        if (!$ready) { throw '3분 안에 Docker 엔진이 준비되지 않았습니다.' }
    }

    & "$PSScriptRoot\prototype.ps1" Start
    if ($LASTEXITCODE -ne 0) { throw '프로토타입 시작 스크립트가 실패했습니다.' }

    $urlFile = Join-Path $projectRoot 'data\deployment\public-url.txt'
    $credentialFile = Join-Path $projectRoot '.secrets\prototype-credentials.json'
    if (!(Test-Path -LiteralPath $urlFile) -or !(Test-Path -LiteralPath $credentialFile)) {
        throw '접속 주소 또는 로컬 인증정보 파일을 찾을 수 없습니다.'
    }
    $url = (Get-Content -Raw -LiteralPath $urlFile).Trim()
    $credentials = Get-Content -Raw -LiteralPath $credentialFile | ConvertFrom-Json
    $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($credentials.username):$($credentials.password)"))
    $healthy = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$url/api/health" -Headers @{Authorization = "Basic $token"} -TimeoutSec 15
            if ($health.status -eq 'ok') { $healthy = $true; break }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if (!$healthy) { throw '외부 HTTPS 상태 점검에 실패했습니다.' }

    Write-Host ''
    Write-Host 'Carbon Urban DSS 외부 테스트 서버가 준비되었습니다.' -ForegroundColor Green
    Write-Host "접속 주소: $url"
    Write-Host '계정: prototype / prototype'
    Write-Host '이 PC, Docker Desktop, 인터넷 연결을 유지하세요.'
    if (!$NoBrowser) { Start-Process $url }
}
catch {
    Write-Host ''
    Write-Host "서버 시작 실패: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Docker Desktop 상태와 인터넷 연결을 확인한 뒤 다시 실행하세요.'
    exit 1
}
