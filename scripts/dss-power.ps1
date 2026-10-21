# Carbon Urban DSS 켜기·끄기 (바탕화면 버튼 'Carbon DSS 켜기'·'Carbon DSS 끄기'가 부릅니다. 설치: scripts\install-power-buttons.ps1)
#   -Mode Off    : 시연 주소 지킴이를 쉬게 하고(data\deployment\demo-watch.paused), 서비스를 차례로 멈춘 뒤 Docker Desktop을 끕니다.
#                  다시 켤 때까지 지킴이·재부팅이 Docker를 켜지 않습니다. DB 자료(볼륨)는 그대로입니다.
#   -Mode On     : 쉬기 표시를 지우고 Docker Desktop을 켠 뒤 DB·API·화면·gateway·터널(·로컬 AI)을 올리고,
#                  새 터널 주소를 GitHub Pages 안내 주소(https://shy0401.github.io/Carbon-Urban-DSS/)에 올립니다.
#   -Mode Status : 지금 상태만 보여 줍니다.
# 이미지를 새로 만들지 않습니다(처음 설치·코드 변경 뒤에는 바탕화면의 'Carbon Urban DSS 서버 실행'을 씁니다). docker compose down -v를 쓰지 않습니다.
param(
    [ValidateSet('On', 'Off', 'Status')][string]$Mode = 'Status',
    [switch]$NoPause
)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$PauseFile = Join-Path $Root 'data\deployment\demo-watch.paused'
$UrlFile = Join-Path $Root 'data\deployment\public-url.txt'
$PagesUrl = 'https://shy0401.github.io/Carbon-Urban-DSS/'
$C = @('compose', '-p', 'carbon-urban-dss', '-f', 'compose.yaml', '-f', 'compose.demo.yaml', '--profile', 'public-demo', '--profile', 'local-ai', '--profile', 'team-model')
$Services = @('postgres', 'redis', 'api', 'worker', 'frontend', 'gateway', 'tunnel')
try { $Host.UI.RawUI.WindowTitle = "Carbon DSS $(@{ On = '켜기'; Off = '끄기'; Status = '상태' }[$Mode])" } catch { }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    foreach ($bin in @('F:\DockerDesktop\App\resources\bin', "$env:ProgramFiles\Docker\Docker\resources\bin", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin")) {
        if (Test-Path -LiteralPath (Join-Path $bin 'docker.exe')) { $env:Path = "$bin;$env:Path"; break }
    }
}

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }

function Invoke-Tool([string]$File, [string[]]$Arguments) {
    $global:LASTEXITCODE = 0
    try { $output = & $File @Arguments 2>&1 } catch { return [pscustomobject]@{ Code = -1; Lines = @("$_") } }
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Code = $code; Lines = @($output | ForEach-Object { "$_" } | Where-Object { $_ -and $_ -ne 'System.Management.Automation.RemoteException' }) }
}

function Test-Engine {
    $r = Invoke-Tool 'docker' @('info', '--format', '{{.ServerVersion}}')
    return [bool]($r.Code -eq 0 -and ($r.Lines | Where-Object { $_ -match '^\d+\.' }))
}

function Test-DesktopCli { return ((Invoke-Tool 'docker' @('desktop', 'version')).Code -eq 0) }

function Get-DesktopExe {
    $candidates = @()
    $cli = Get-Command docker -ErrorAction SilentlyContinue
    if ($cli) { $candidates += (Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $cli.Source))) 'Docker Desktop.exe') }
    $candidates += @('F:\DockerDesktop\App\Docker Desktop.exe', "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe")
    return ($candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1)
}

function Get-States {
    $map = @{}
    $r = Invoke-Tool 'docker' ($C + @('ps', '-a', '--format', '{{.Service}} {{.State}}'))
    foreach ($line in $r.Lines) { $p = $line.Trim() -split '\s+'; if ($p.Count -ge 2) { $map[$p[0]] = $p[1] } }
    return $map
}

function Show-Status {
    $paused = Test-Path -LiteralPath $PauseFile
    $engine = Test-Engine
    Say ''
    Say ("Docker 엔진      : " + $(if ($engine) { '켜짐' } else { '꺼짐' })) $(if ($engine) { 'Green' } else { 'Yellow' })
    Say ("자동 켜기(지킴이): " + $(if ($paused) { '쉬는 중 - Docker를 스스로 켜지 않음' } else { '켜짐 - 로그온 때 켜고 멈춘 서비스를 다시 올림(작업 표시줄에서 Docker를 직접 끄면 쉼)' }))
    if ($engine) {
        $states = Get-States
        $line = ($Services + @('ollama', 'team-model') | Where-Object { $states.ContainsKey($_) } | ForEach-Object { "$_=$($states[$_])" }) -join ', '
        Say ("서비스          : " + $line)
    }
}

function Finish([int]$Code) {
    if (-not $NoPause) {
        if ($Code -eq 0) { Say ''; Say '10초 뒤 이 창이 닫힙니다.' 'DarkGray'; Start-Sleep -Seconds 10 }
        else { Say ''; [void](Read-Host 'Enter를 누르면 이 창이 닫힙니다') }
    }
    exit $Code
}

if ($Mode -eq 'Status') { Show-Status; Finish 0 }

if ($Mode -eq 'Off') {
    Say 'Carbon Urban DSS를 끕니다.' 'Cyan'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PauseFile) | Out-Null
    Set-Content -LiteralPath $PauseFile -Value ("off button " + (Get-Date).ToString('s')) -Encoding ascii
    Say '1/3 자동 켜기를 멈췄습니다(다시 켤 때까지 Docker를 스스로 켜지 않음).'
    if (Test-Engine) {
        Say '2/3 서비스를 차례로 멈춥니다(DB 안전 종료, 1분쯤)...'
        $r = Invoke-Tool 'docker' ($C + @('stop', '--timeout', '30'))
        if ($r.Code -eq 0) { Say '    멈춤' } else { Say ("    멈추기 경고(exit $($r.Code)): " + (($r.Lines | Select-Object -Last 2) -join ' | ')) 'Yellow' }
        Say '3/3 Docker Desktop을 끕니다...'
        $stopped = $false
        if (Test-DesktopCli) {
            $r = Invoke-Tool 'docker' @('desktop', 'stop')
            if ($r.Code -ne 0) { $r = Invoke-Tool 'docker' @('desktop', 'stop', '--force') }
            $stopped = ($r.Code -eq 0)
        }
        if (-not $stopped) {
            Get-Process -Name 'Docker Desktop', 'com.docker.backend', 'com.docker.build' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            [void](Invoke-Tool 'wsl.exe' @('--terminate', 'docker-desktop'))
        }
        for ($i = 0; $i -lt 30 -and (Test-Engine); $i++) { Start-Sleep -Seconds 2 }
    } else {
        Say '2/3 Docker 엔진은 이미 꺼져 있습니다.'
        Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue | ForEach-Object { if (Test-DesktopCli) { [void](Invoke-Tool 'docker' @('desktop', 'stop', '--force')) } else { $_ | Stop-Process -Force -ErrorAction SilentlyContinue } }
        Say '3/3 Docker Desktop 창도 닫았습니다.'
    }
    if (Test-Engine) {
        Say 'Docker 엔진이 아직 켜져 있습니다. 작업 표시줄의 Docker 아이콘에서 Quit Docker Desktop을 눌러 주세요(지킴이는 쉬는 중이라 다시 켜지 않습니다).' 'Yellow'
        Show-Status; Finish 1
    }
    Say ''
    Say '꺼졌습니다. 재부팅해도 자동으로 켜지지 않습니다. 다시 켜려면 바탕화면의 [Carbon DSS 켜기]를 누르세요.' 'Green'
    Say "시연 안내 주소($PagesUrl)는 '연결되지 않습니다'로 보입니다."
    Finish 0
}

# On
Say 'Carbon Urban DSS를 켭니다. 2~4분 걸립니다.' 'Cyan'
Remove-Item -LiteralPath $PauseFile -Force -ErrorAction SilentlyContinue
Say '1/4 자동 켜기를 다시 켰습니다(로그온·재부팅 뒤 스스로 켜고, 멈춘 서비스는 5분 안에 다시 올림).'
if (-not (Test-Engine)) {
    Say '2/4 Docker Desktop을 켭니다...'
    $launched = $false
    if (Test-DesktopCli) { $r = Invoke-Tool 'docker' @('desktop', 'start', '--detach'); $launched = ($r.Code -eq 0) }
    if (-not $launched) {
        $exe = Get-DesktopExe
        if (-not $exe) { Say 'Docker Desktop 실행 파일을 찾지 못했습니다. Docker Desktop을 직접 켠 뒤 다시 누르세요.' 'Red'; Finish 1 }
        Start-Process -FilePath $exe | Out-Null
    }
    $ready = $false
    for ($i = 1; $i -le 100; $i++) {
        Start-Sleep -Seconds 3
        if (Test-Engine) { $ready = $true; break }
        if ($i % 10 -eq 0) { Say "    기다리는 중 ($($i * 3)초)" 'DarkGray' }
    }
    if (-not $ready) { Say 'Docker 엔진이 5분 안에 준비되지 않았습니다. Docker Desktop 창의 메시지를 확인한 뒤 다시 누르세요.' 'Red'; Finish 1 }
    Say '    Docker 엔진 준비됨'
} else {
    Say '2/4 Docker 엔진은 이미 켜져 있습니다.'
}
Say '3/4 DB·API·화면·공개 연결을 올립니다...'
$states = Get-States
$targets = @($Services)
if ($states.ContainsKey('ollama')) { $targets += 'ollama' }
if ($states.ContainsKey('team-model')) { $targets += 'team-model' }  # 팀 변화 모델: 팀 인계 묶음이 있는 PC에서 한 번 만든 뒤에만
$r = Invoke-Tool 'docker' ($C + @('up', '-d', '--no-build', '--wait', '--wait-timeout', '300') + $targets)
if ($r.Code -ne 0) {
    Say ("    올리기 실패(exit $($r.Code)): " + (($r.Lines | Select-Object -Last 3) -join ' | ')) 'Red'
    Say '    처음 설치했거나 코드가 바뀌어 이미지가 없으면 바탕화면의 [Carbon Urban DSS 서버 실행]을 쓰세요.' 'Yellow'
    Show-Status; Finish 1
}
Say '    올라옴'
Say '4/4 새 시연 주소를 GitHub Pages 안내 주소에 올립니다...'
$watch = Join-Path $PSScriptRoot 'demo-watch.ps1'
$w = Invoke-Tool 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watch, '-Publish')
$w.Lines | ForEach-Object { Say ('    ' + ($_ -replace '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+', '')) 'DarkGray' }
if ($w.Code -ne 0) { Say '    안내 주소 갱신이 실패했습니다. 5분마다 지킴이가 다시 시도합니다(data\ops\demo-watch.log).' 'Yellow' }
Say ''
Say '켜졌습니다.' 'Green'
Say '  이 PC에서 : http://localhost:5173/'
Say "  밖에서    : $PagesUrl  (새 주소 반영까지 1분쯤, 시연 계정 로그인 필요)"
Finish 0
