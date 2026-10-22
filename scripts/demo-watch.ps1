# 시연 주소 지킴이. 작업 스케줄러가 Windows 로그온 때와 5분마다 실행합니다(scripts\install-demo-watch.ps1로 등록).
# - Docker 엔진이 꺼져 있으면 Docker Desktop을 켜고, 멈춘 서비스(DB·API·화면·gateway·터널)를 다시 올립니다.
# - Cloudflare 빠른 터널(trycloudflare) 주소를 읽어 바깥에서 열리는지 봅니다. 두 번 연속 안 열리면 터널만 다시 시작합니다.
# - 주소가 바뀌었거나 안내 페이지가 바뀌었거나 -Publish를 주면 GitHub Pages(gh-pages 브랜치)의 demo.json을 고쳐 올립니다.
#   고정 안내 주소 https://shy0401.github.io/Carbon-Urban-DSS/ 는 demo.json을 읽어 지금의 시연 주소로 보냅니다.
# 로그(data\ops\demo-watch.log)에는 주소·계정·토큰을 적지 않습니다. 강제 푸시·기록 다시 쓰기를 하지 않습니다.
# 쉬게 하기: data\deployment\demo-watch.paused 파일이 있으면 아무것도 하지 않습니다. 바탕화면 [Carbon DSS 끄기](scripts\dss-power.ps1 -Mode Off)·
#   scripts\prototype.ps1 Stop이 만들고 [Carbon DSS 켜기]·prototype.ps1 Start가 지웁니다.
#   같은 로그온 동안 켜져 있던 Docker Desktop을 사람이 직접 끄면(작업 표시줄 Quit) 그 뜻으로 보고 스스로 쉽니다. 재부팅·새 로그온 뒤에는 다시 켭니다.
# - Claude 작업 실행기(data\ops\claude-runner\runner.ps1)가 멈춰 있으면(heartbeat.txt가 3분 넘게 그대로) 최소화 창으로 다시 켭니다.
#   쉬기(paused)와 무관하게 봅니다. 끄려면 data\ops\claude-runner\autostart.off 파일을 두거나 stop.flag로 멈춥니다.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$Publish,
    [switch]$NoStart
)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
# 숨은 창에서 Git 자격 증명 창이 떠 멈추지 않게 합니다. 저장된 자격 증명이 없으면 푸시가 실패하고 로그에 남습니다.
$env:GCM_INTERACTIVE = 'never'
$env:GIT_TERMINAL_PROMPT = '0'
Set-Location -LiteralPath $Root

$OpsDir = Join-Path $Root 'data\ops'
$LogFile = Join-Path $OpsDir 'demo-watch.log'
$StateFile = Join-Path $OpsDir 'demo-watch-state.json'
$PagesDir = Join-Path $OpsDir 'pages-site'
$PagesSource = Join-Path $Root 'deploy\pages'
$PageFiles = @('index.html', '404.html', '.nojekyll')
$UrlFile = Join-Path $Root 'data\deployment\public-url.txt'
$PauseFile = Join-Path $Root 'data\deployment\demo-watch.paused'
$C = @('compose', '-p', 'carbon-urban-dss', '-f', 'compose.yaml', '-f', 'compose.demo.yaml', '--profile', 'public-demo')
$Services = @('postgres', 'redis', 'api', 'worker', 'frontend', 'gateway', 'tunnel')
$UrlPattern = 'https://[a-z0-9-]+\.trycloudflare\.com'
New-Item -ItemType Directory -Force -Path $OpsDir | Out-Null

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    foreach ($bin in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin")) {
        if (Test-Path -LiteralPath (Join-Path $bin 'docker.exe')) { $env:Path = "$bin;$env:Path"; break }
    }
}

function Write-Log([string]$Text) {
    $line = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + '  ' + ($Text -replace $UrlPattern, '<demo-url>')
    try {
        if ((Test-Path -LiteralPath $LogFile) -and ((Get-Item -LiteralPath $LogFile).Length -gt 512KB)) {
            $keep = @(Get-Content -LiteralPath $LogFile -Encoding UTF8 | Select-Object -Last 2000)
            Set-Content -LiteralPath $LogFile -Value $keep -Encoding UTF8
        }
        Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    } catch { }
    Write-Host $line
}

function Invoke-Tool([string]$File, [string[]]$Arguments) {
    # stderr 진행 표시 때문에 멈추지 않게 실행하고 종료 코드와 줄을 돌려줍니다.
    $global:LASTEXITCODE = 0
    try { $output = & $File @Arguments 2>&1 } catch { return [pscustomobject]@{ Code = -1; Lines = @("$_"); Text = "$_" } }
    $code = $LASTEXITCODE
    $lines = @($output | ForEach-Object { "$_" } | Where-Object { $_ -and $_ -ne 'System.Management.Automation.RemoteException' })
    return [pscustomobject]@{ Code = $code; Lines = $lines; Text = ($lines -join "`n") }
}

function Read-State {
    $s = [ordered]@{ published_url = $null; published_at = $null; page_hash = $null; tunnel_ticks = $null; tunnel_url = $null; fails = 0; last_restart = $null; engine_session = $null }
    if (Test-Path -LiteralPath $StateFile) {
        try {
            $j = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($k in @($s.Keys)) { if ($null -ne $j.$k) { $s[$k] = $j.$k } }
        } catch { }
    }
    return $s
}

function Save-State($s) {
    try { ($s | ConvertTo-Json) | Set-Content -LiteralPath $StateFile -Encoding UTF8 } catch { Write-Log "state save failed: $($_.Exception.Message)" }
}

function Test-Engine {
    $r = Invoke-Tool 'docker' @('info', '--format', '{{.ServerVersion}}')
    return [bool]($r.Code -eq 0 -and ($r.Lines | Where-Object { $_ -match '^\d+\.' }))
}

function Start-Engine {
    if (Test-Engine) { return $true }
    if ($NoStart) { Write-Log 'docker engine is down (-NoStart: not starting it)'; return $false }
    if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        $candidates = @()
        $cli = Get-Command docker -ErrorAction SilentlyContinue
        if ($cli) { $candidates += (Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $cli.Source))) 'Docker Desktop.exe') }
        $candidates += @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe")
        $desktop = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if (-not $desktop) { Write-Log 'Docker Desktop not found: start it by hand'; return $false }
        Write-Log 'docker engine is down: starting Docker Desktop'
        Start-Process -FilePath $desktop | Out-Null
    } else {
        Write-Log 'docker engine is down: Docker Desktop is already starting, waiting'
    }
    for ($i = 1; $i -le 60; $i++) {
        Start-Sleep -Seconds 5
        if (Test-Engine) { Write-Log "docker engine ready after about $($i * 5) s"; Start-Sleep -Seconds 20; return $true }
    }
    Write-Log 'docker engine not ready after 5 min (the next run tries again)'
    return $false
}

function Get-States {
    $map = @{}
    $r = Invoke-Tool 'docker' ($C + @('ps', '-a', '--format', '{{.Service}} {{.State}}'))
    if ($r.Code -ne 0) { return $map }
    foreach ($line in $r.Lines) { $p = $line.Trim() -split '\s+'; if ($p.Count -ge 2) { $map[$p[0]] = $p[1] } }
    return $map
}

function Get-Down($map) { return @($Services | Where-Object { $map[$_] -ne 'running' }) }

function Get-Tunnel {
    $info = [ordered]@{ Id = $null; Started = $null; StartedUtc = $null; Ticks = $null; Url = $null }
    $id = @((Invoke-Tool 'docker' ($C + @('ps', '-q', 'tunnel'))).Lines | Where-Object { $_ -match '^[0-9a-f]{12,}$' }) | Select-Object -First 1
    if (-not $id) { return $info }
    $info.Id = $id
    $started = @((Invoke-Tool 'docker' @('inspect', '-f', '{{.State.StartedAt}}', $id)).Lines) | Select-Object -First 1
    if ($started -match '^\d{4}-\d{2}-\d{2}T') {
        $info.Started = $started.Trim()
        try {
            $info.StartedUtc = [DateTime]::Parse(($info.Started -replace '(\.\d{1,7})\d*', '$1'), [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)
            $info.Ticks = [string]$info.StartedUtc.Ticks
        } catch { }
    }
    $logArgs = @('logs')
    if ($info.Started) { $logArgs += @('--since', $info.Started) }
    $logArgs += $id
    $text = (Invoke-Tool 'docker' $logArgs).Text
    $found = @([regex]::Matches($text, $UrlPattern) | ForEach-Object { $_.Value } | Where-Object { $_ -ne 'https://api.trycloudflare.com' })
    if ($found.Count) { $info.Url = $found[$found.Count - 1] }
    return $info
}

function Test-Reachable([string]$Url) {
    # 로그인 없이 열리는 /__ping(204)을 묻습니다. 500 미만이면 터널과 gateway가 살아 있는 것으로 봅니다(예전 설정이면 401).
    try {
        $req = [Net.HttpWebRequest]::Create("$Url/__ping?t=" + [DateTime]::UtcNow.Ticks)
        $req.Method = 'GET'; $req.Timeout = 15000; $req.AllowAutoRedirect = $false; $req.UserAgent = 'carbon-dss-demo-watch'
        $resp = $req.GetResponse(); $code = [int]$resp.StatusCode; $resp.Close()
        return ($code -lt 500)
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode; $_.Exception.Response.Close(); return ($code -lt 500) }
        return $false
    } catch { return $false }
}

function Get-PageHash {
    $parts = foreach ($f in $PageFiles) {
        $p = Join-Path $PagesSource $f
        if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash } else { 'missing' }
    }
    return ($parts -join '-')
}

function Invoke-Git([string[]]$Arguments) { return Invoke-Tool 'git' (@('-C', $PagesDir) + $Arguments) }

function Publish-Pages([string]$Url) {
    foreach ($f in $PageFiles) { if (-not (Test-Path -LiteralPath (Join-Path $PagesSource $f))) { Write-Log "pages: deploy\pages\$f is missing"; return $false } }
    $remote = @((Invoke-Tool 'git' @('-C', $Root, 'remote', 'get-url', 'origin')).Lines) | Select-Object -First 1
    if (-not $remote) { Write-Log 'pages: the repository has no origin remote'; return $false }
    $heads = Invoke-Tool 'git' @('ls-remote', '--heads', $remote, 'gh-pages')
    if ($heads.Code -ne 0) { Write-Log "pages: cannot reach the GitHub repository (git ls-remote exit $($heads.Code))"; return $false }
    $remoteHas = [bool]($heads.Text -match 'refs/heads/gh-pages')
    if (-not (Test-Path -LiteralPath (Join-Path $PagesDir '.git'))) {
        if ((Test-Path -LiteralPath $PagesDir) -and @(Get-ChildItem -LiteralPath $PagesDir -Force).Count) { Write-Log 'pages: data\ops\pages-site exists but is not a git folder; move it away'; return $false }
        if ($remoteHas) {
            $r = Invoke-Tool 'git' @('clone', '--quiet', '--branch', 'gh-pages', '--single-branch', $remote, $PagesDir)
            if ($r.Code -ne 0) { Write-Log "pages: clone of gh-pages failed (exit $($r.Code))"; return $false }
        } else {
            New-Item -ItemType Directory -Force -Path $PagesDir | Out-Null
            $r = Invoke-Tool 'git' @('init', '--quiet', $PagesDir)
            if ($r.Code -ne 0) { Write-Log "pages: git init failed (exit $($r.Code))"; return $false }
            [void](Invoke-Git @('symbolic-ref', 'HEAD', 'refs/heads/gh-pages'))
            [void](Invoke-Git @('remote', 'add', 'origin', $remote))
            Write-Log 'pages: starting a new gh-pages branch'
        }
    } elseif ($remoteHas) {
        $r = Invoke-Git @('pull', '--quiet', '--ff-only', 'origin', 'gh-pages')
        if ($r.Code -ne 0) { Write-Log "pages: local gh-pages cannot fast-forward to GitHub (exit $($r.Code)); fix data\ops\pages-site by hand"; return $false }
    }
    if (-not (@((Invoke-Git @('config', 'user.email')).Lines) | Select-Object -First 1)) {
        $name = @((Invoke-Tool 'git' @('-C', $Root, 'config', 'user.name')).Lines) | Select-Object -First 1
        $mail = @((Invoke-Tool 'git' @('-C', $Root, 'config', 'user.email')).Lines) | Select-Object -First 1
        if (-not $name) { $name = 'shy0401' }
        if (-not $mail) { $mail = '166055700+shy0401@users.noreply.github.com' }
        [void](Invoke-Git @('config', 'user.name', $name))
        [void](Invoke-Git @('config', 'user.email', $mail))
    }
    foreach ($f in $PageFiles) { Copy-Item -LiteralPath (Join-Path $PagesSource $f) -Destination (Join-Path $PagesDir $f) -Force }
    $kst = [DateTime]::UtcNow.AddHours(9)
    $demo = [ordered]@{
        url = $Url
        updated_at = $kst.ToString("yyyy-MM-dd'T'HH:mm:ss") + '+09:00'
        note = 'Carbon Urban DSS 시연 서버 주소. 연구실 PC의 scripts/demo-watch.ps1이 터널 주소가 바뀔 때 고칩니다. 들어가면 시연 계정 로그인이 필요합니다.'
    }
    [IO.File]::WriteAllText((Join-Path $PagesDir 'demo.json'), (($demo | ConvertTo-Json) + "`n"), (New-Object System.Text.UTF8Encoding($false)))
    [void](Invoke-Git @('add', '-A'))
    $st = Invoke-Git @('status', '--porcelain')
    if ($st.Lines.Count) {
        $commitArgs = @('commit', '--quiet', '-m', ('Update demo address (' + $kst.ToString('yyyy-MM-dd HH:mm') + ' KST)'))
        if ($env:DEMO_WATCH_COMMIT_NOTE) { $commitArgs += @('-m', $env:DEMO_WATCH_COMMIT_NOTE) }
        $r = Invoke-Git $commitArgs
        if ($r.Code -ne 0) { Write-Log "pages: commit failed (exit $($r.Code)): $(($r.Lines | Select-Object -Last 2) -join ' | ')"; return $false }
    }
    $r = Invoke-Git @('push', '--quiet', 'origin', 'gh-pages')
    if ($r.Code -ne 0) { Write-Log ("pages: push failed (exit $($r.Code)): " + ((($r.Lines | Select-Object -Last 2) -join ' | ') -replace 'https://[^\s/@]+@', 'https://')); return $false }
    Write-Log 'pages: demo.json pushed to gh-pages (GitHub Pages refreshes in about a minute)'
    return $true
}

function Start-Runner {
    # Claude 작업 실행기가 죽어 있으면(창을 닫음·재부팅·8일 만료) 다시 켠다. 사람이 autostart.off를 두면 하지 않는다.
    $runnerDir = Join-Path $Root 'data\ops\claude-runner'
    $script = Join-Path $runnerDir 'runner.ps1'
    if (-not (Test-Path -LiteralPath $script)) { return }
    if (Test-Path -LiteralPath (Join-Path $runnerDir 'autostart.off')) { return }
    if (Test-Path -LiteralPath (Join-Path $runnerDir 'stop.flag')) { return }
    $beat = Join-Path $runnerDir 'heartbeat.txt'
    $age = if (Test-Path -LiteralPath $beat) { (Get-Date) - (Get-Item -LiteralPath $beat).LastWriteTime } else { [TimeSpan]::FromDays(1) }
    if ($age.TotalMinutes -lt 3) { return }
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script) -WorkingDirectory $runnerDir -WindowStyle Minimized | Out-Null
        Write-Log ('runner restarted (heartbeat was ' + [int]$age.TotalMinutes + ' min old)')
    } catch { Write-Log "runner restart failed: $($_.Exception.Message)" }
}

function Get-SessionMark {
    # 이번 Windows 로그온을 가리키는 값: 가장 먼저 뜬 explorer.exe의 시작 시각(재부팅·로그오프 뒤 바뀜).
    $first = Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object { $_.StartTime } | Sort-Object StartTime | Select-Object -First 1
    if ($first) { return [string]$first.StartTime.ToUniversalTime().Ticks }
    return $null
}

function Invoke-Watch {
    Start-Runner
    if (Test-Path -LiteralPath $PauseFile) {
        if ($Publish) { Write-Log 'paused (data\deployment\demo-watch.paused exists): nothing done' }
        return 0
    }
    $exitCode = 0
    $state = Read-State
    $session = Get-SessionMark
    if (-not (Test-Engine)) {
        $desktopRunning = [bool](Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)
        if (-not $Publish -and -not $desktopRunning -and $session -and [string]$state.engine_session -eq $session) {
            # 이번 로그온에서 켜져 있던 Docker를 누가 껐음 → 다시 켜지 않고 쉼
            Set-Content -LiteralPath $PauseFile -Value ('paused: Docker Desktop was closed by hand ' + (Get-Date).ToString('s')) -Encoding ascii
            Write-Log 'Docker Desktop was closed by hand in this logon: the watcher now leaves it off (press [Carbon DSS 켜기] to turn everything back on)'
            return 0
        }
    }
    if (-not (Start-Engine)) { return 1 }
    if ($session) { $state.engine_session = $session }

    $states = Get-States
    $down = @(Get-Down $states)
    if ($down.Count) {
        Write-Log ('not running: ' + (($down | ForEach-Object { if ($states[$_]) { "$_($($states[$_]))" } else { "$_(none)" } }) -join ', '))
        # 부팅 직후에는 Docker가 unless-stopped 컨테이너를 스스로 다시 올리므로 1분 기다렸다가 그래도 멈춘 것만 올립니다.
        Start-Sleep -Seconds 60
        $states = Get-States
        $down = @(Get-Down $states)
        if ($down.Count) {
            $r = Invoke-Tool 'docker' ($C + @('up', '-d', '--no-build') + $down)
            Write-Log "docker compose up -d --no-build $($down -join ' '): exit $($r.Code)"
            if ($r.Code -ne 0) { Write-Log ('  ' + (($r.Lines | Select-Object -Last 3) -join ' | ')) }
        } else {
            Write-Log 'all services came back on their own'
        }
    }

    $t = Get-Tunnel
    # 터널 로그가 돌아가 주소 줄이 지워졌어도 같은 컨테이너 실행이면 앞서 읽은 주소를 씁니다.
    if (-not $t.Url -and $t.Ticks -and [string]$state.tunnel_ticks -eq $t.Ticks -and $state.tunnel_url) { $t.Url = $state.tunnel_url }
    $ok = $false
    if ($t.Url) {
        $ok = Test-Reachable $t.Url
        if (-not $ok) { Start-Sleep -Seconds 20; $ok = Test-Reachable $t.Url }
    }
    if (-not $ok) {
        $state.fails = [int]$state.fails + 1
        $why = if (-not $t.Id) { 'tunnel container not running' } elseif (-not $t.Url) { 'no address in the tunnel log' } else { 'address does not answer' }
        Write-Log "demo address check failed ($why), $($state.fails) in a row"
        $age = if ($t.StartedUtc) { ((Get-Date).ToUniversalTime() - $t.StartedUtc).TotalMinutes } else { 999 }
        $sinceRestart = 999
        if ($state.last_restart) { try { $sinceRestart = ((Get-Date).ToUniversalTime() - [DateTime]::new([long]$state.last_restart, [DateTimeKind]::Utc)).TotalMinutes } catch { } }
        # 새 터널이 자리 잡을 시간(10분)과 다시 시작 간격(30분)을 두어 주소를 계속 바꾸는 일을 막습니다.
        if ($t.Id -and $state.fails -ge 2 -and $age -ge 10 -and $sinceRestart -ge 30) {
            $r = Invoke-Tool 'docker' ($C + @('restart', 'tunnel'))
            $state.last_restart = [string](Get-Date).ToUniversalTime().Ticks
            Write-Log "restarted the quick tunnel only (app and DB untouched): exit $($r.Code)"
            # 다시 시작하면 StartedAt이 바뀌어 Get-Tunnel은 새 실행의 로그에서만 주소를 찾습니다.
            $n = $null
            for ($i = 0; $i -lt 15; $i++) {
                Start-Sleep -Seconds 4
                $n = Get-Tunnel
                if ($n.Url) { break }
            }
            $t = $n
            if ($t -and $t.Url) {
                for ($i = 0; $i -lt 6 -and -not $ok; $i++) { Start-Sleep -Seconds 10; $ok = Test-Reachable $t.Url }
            } else {
                Write-Log 'no new address in the tunnel log yet'
            }
        }
    }
    if ($t.Url) {
        if ($t.Ticks) { $state.tunnel_ticks = $t.Ticks; $state.tunnel_url = $t.Url }
        $current = if (Test-Path -LiteralPath $UrlFile) { ([string](Get-Content -LiteralPath $UrlFile -Raw)).Trim() } else { '' }
        if ($current -ne $t.Url) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $UrlFile) | Out-Null
            Set-Content -LiteralPath $UrlFile -Value $t.Url -Encoding ascii -NoNewline
            Write-Log 'data\deployment\public-url.txt now holds the new address'
        }
        $pageHash = Get-PageHash
        $reasons = @()
        if ($Publish) { $reasons += 'asked (-Publish)' }
        if ($state.published_url -ne $t.Url) { $reasons += 'address changed' }
        if ($state.page_hash -ne $pageHash) { $reasons += 'landing page changed' }
        if ($reasons.Count) {
            # 주소가 바뀌면 옛 주소는 이미 죽었으므로, 새 주소가 아직 응답하지 않아도 올립니다(안내 페이지가 접속 여부를 다시 확인).
            Write-Log ('publishing to GitHub Pages: ' + ($reasons -join ', ') + $(if ($ok) { '' } else { ' (new address not answering yet)' }))
            if (Publish-Pages $t.Url) { $state.published_url = $t.Url; $state.published_at = (Get-Date).ToString('o'); $state.page_hash = $pageHash } else { $exitCode = 2 }
        }
    }
    if ($ok) {
        if ([int]$state.fails -gt 0) { Write-Log 'demo address answers again' }
        $state.fails = 0
    }
    Save-State $state
    return $exitCode
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\CarbonDssDemoWatch')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) { Write-Log 'another run is still going: skip'; exit 0 }
$code = 1
try { $code = Invoke-Watch } catch { Write-Log "unexpected error: $($_.Exception.Message)" } finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
}
exit $code
