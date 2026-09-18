param(
    [string]$Model = 'qwen2.5:1.5b',
    [switch]$SkipContainerStart
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$composeArgs = @('compose', '-f', 'compose.yaml', '-f', 'compose.demo.yaml', '--profile', 'local-ai')

function Invoke-Compose {
    & docker @composeArgs @args
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose 명령이 실패했습니다.' }
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker 엔진이 실행 중이 아닙니다.' }

if (!$SkipContainerStart) {
    Invoke-Compose up -d ollama
}

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    & docker @composeArgs exec -T ollama ollama list *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (!$ready) { throw 'Ollama 컨테이너가 준비되지 않았습니다.' }

& docker @composeArgs exec -T ollama ollama show $Model *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "로컬 모델을 최초 다운로드합니다: $Model"
    Invoke-Compose exec -T ollama ollama pull $Model
}

& docker @composeArgs exec -T ollama ollama show $Model *> $null
if ($LASTEXITCODE -ne 0) { throw "로컬 모델 검증에 실패했습니다: $Model" }

Write-Host "로컬 LLM 준비 완료: $Model (Docker 내부 전용)"
