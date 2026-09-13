param(
    [ValidateSet('Start','Stop','Status')][string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$composeArgs = @('compose','-f','compose.yaml','-f','compose.demo.yaml','--profile','local-ai','--profile','public-demo')
function Invoke-Compose {
    & docker @composeArgs @args
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose command failed. Check Docker Desktop and the message above.' }
}

if ($Action -eq 'Stop') {
    Invoke-Compose stop tunnel gateway
    Write-Host 'Public access stopped. Local application and database are preserved.'
    exit
}

if ($Action -eq 'Start') {
    if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    # Do not start any public connector until local credentials exist.
    Invoke-Compose up -d --build --wait postgres redis api worker frontend ollama
    New-Item -ItemType Directory -Force -Path '.secrets' | Out-Null
    $credentialFile = '.secrets/prototype-credentials.json'
    if (!(Test-Path -LiteralPath $credentialFile)) {
        $randomBytes = New-Object byte[] 24
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
        $password = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
        @{username='prototype';password=$password} | ConvertTo-Json | Set-Content -LiteralPath $credentialFile -Encoding utf8
    }
    $credentials = Get-Content -Raw -LiteralPath $credentialFile | ConvertFrom-Json
    if ($credentials.username -ne 'prototype' -or $credentials.password -notmatch '^[A-Za-z0-9_-]{32}$') { throw 'Invalid local credential file.' }
    # Pass the password through stdin, never command arguments or logs.
    $hashCommand = 'import subprocess,sys; print(subprocess.check_output(["openssl","passwd","-6","-stdin"],input=sys.stdin.buffer.read().rstrip(b"\r\n")).decode().strip())'
    $hash = $credentials.password | & docker @composeArgs exec -T api python -c $hashCommand
    if ($LASTEXITCODE -ne 0 -or $hash -notmatch '^\$6\$') { throw 'Password hash generation failed.' }
    'prototype:' + $hash.Trim() | Set-Content -LiteralPath '.secrets/gateway.htpasswd' -Encoding ascii
    & docker @composeArgs exec -T ollama ollama show qwen2.5:1.5b *> $null
    if ($LASTEXITCODE -ne 0) { Invoke-Compose exec -T ollama ollama pull qwen2.5:1.5b }
    Invoke-Compose exec -T api python -m app.cli online
    $system = Invoke-RestMethod 'http://127.0.0.1:8000/api/system'
    if ($system.offline_mode) { throw 'DEMO_OFFLINE_MODE forces offline. Remove it from .env and recreate api/worker before starting public access.' }
    Invoke-Compose up -d --wait gateway
    Invoke-Compose up -d tunnel
}

$url = $null
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $logs = & docker @composeArgs logs --no-color --tail 100 tunnel 2>&1 | Out-String
    $matchesFound = [regex]::Matches($logs, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($matchesFound.Count) { $url = $matchesFound[$matchesFound.Count - 1].Value; break }
    if ($Action -eq 'Status') { break }
    Start-Sleep -Seconds 2
}
if (!$url) { throw 'No public URL yet. Run scripts/prototype.ps1 Status after the tunnel connects.' }
New-Item -ItemType Directory -Force -Path 'data/deployment' | Out-Null
$url | Set-Content -LiteralPath 'data/deployment/public-url.txt' -Encoding ascii
$credentials = Get-Content -Raw -LiteralPath '.secrets/prototype-credentials.json' | ConvertFrom-Json
@"
# Carbon Urban DSS prototype access

URL: $url

Username: $($credentials.username)

Password: $($credentials.password)

Keep this file private. Do not commit or share the entire .secrets directory.
Share credentials only with intended reviewers. They can collect, upload and create reports.
PC, Docker Desktop and network must remain running. The URL can change after tunnel recreation.
Start: powershell -File scripts/prototype.ps1 Start
Stop public access: powershell -File scripts/prototype.ps1 Stop
Current URL: powershell -File scripts/prototype.ps1 Status
"@ | Set-Content -LiteralPath '.secrets/prototype-access.md' -Encoding utf8
Write-Host "URL: $url"
Write-Host 'Access credentials: .secrets/prototype-access.md (never uploaded to GitHub)'
