<#
Carbon Urban DSS operations runner (Windows PowerShell 5.1+ / PowerShell 7).

  powershell -ExecutionPolicy Bypass -File scripts\dss.ps1 -Action All
  scripts\dss.cmd All

Actions
  Doctor        PC/Docker/.env/port/disk pre-check (never prints secret values)
  Status        DB table counts, raw files, readiness (JSON)
  Backup        pg_dump (public schema) + table counts + raw manifest + SHA-256
  Rebuild       rebuild and restart api/worker/frontend with the current code
  Probe         minimal real SGIS / VWorld requests, sanitized structure report
  Collect       staged SMOKE -> LIMITED -> FULL collection (stops on first failure)
                -RetryRejected: retry now after a key registration was fixed
  VerifyRestore restore the latest backup into a separate throwaway project,
                compare every table count, run pytest and (optionally) browser E2E
  FrontendTest  Vitest + production build inside Linux (docker build --target test)
  ExportBundle  team share bundle: DB dump + data/raw (+uploads) + checksums
  ImportBundle  import a bundle into an EMPTY database on a new PC (-BundlePath)
  All           Doctor, Backup, Rebuild, Status, Probe, Collect, Status, Backup,
                VerifyRestore(+pytest,+E2E), FrontendTest

Safety
  * The main project's volumes are never removed. Only the throwaway project
    'carbon-urban-dss-restoretest' is cleaned up after verification.
  * .env, .secrets, data/cache, data/deployment and Ollama models are never
    copied into backups or bundles.
  * Results are written to data/ops/<timestamp>-<action>/ (summary.json, *.log).
#>
param(
    [ValidateSet('All', 'Doctor', 'Status', 'Backup', 'Rebuild', 'Probe', 'Collect', 'VerifyRestore', 'FrontendTest', 'E2E', 'ExportBundle', 'ImportBundle')]
    [string]$Action = 'All',
    [string]$BundlePath,
    [string]$BackupDir,
    [switch]$IncludeUploads,
    [switch]$SkipE2E,
    [switch]$SkipCollect,
    [switch]$KeepRestoreProject,
    [switch]$RetryRejected
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    # A mouse click in a console with QuickEdit pauses all output and blocks this script; disable it for this window.
    Add-Type -Namespace DssWin32 -Name Console -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int handle);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr handle, out uint mode);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr handle, uint mode);
'@ -ErrorAction Stop
    $consoleInput = [DssWin32.Console]::GetStdHandle(-10)
    $consoleMode = [uint32]0
    if ([DssWin32.Console]::GetConsoleMode($consoleInput, [ref]$consoleMode)) {
        [void][DssWin32.Console]::SetConsoleMode($consoleInput, (($consoleMode -band (-bnot [uint32]0x40)) -bor [uint32]0x80))
    }
} catch { }

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$MainProject = 'carbon-urban-dss'
$RestoreProject = 'carbon-urban-dss-restoretest'
$PlaywrightImage = 'mcr.microsoft.com/playwright:v1.55.0-noble'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$RunName = "$Stamp-$($Action.ToLower())"
$RunDir = Join-Path $Root (Join-Path 'data\ops' $RunName)
$ContainerRunDir = "/data/ops/$RunName"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
Set-Content -LiteralPath (Join-Path $Root 'data\ops\latest.txt') -Value $RunName -Encoding ASCII
$Log = Join-Path $RunDir 'run.log'
$Summary = [ordered]@{ action = $Action; run = $RunName; started_at = (Get-Date).ToString('o'); steps = @(); results = [ordered]@{} }

function Save-Summary {
    $Summary.updated_at = (Get-Date).ToString('o')
    $Summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RunDir 'summary.json') -Encoding UTF8
}

function Write-Log([string]$Text) {
    Add-Content -LiteralPath $Log -Value $Text -Encoding UTF8
    Write-Host $Text
}

function Invoke-Native {
    # Runs a native command without letting stderr progress output abort the script.
    param([string]$File, [string[]]$Arguments, [string]$StepLog = $Log, [string]$InputText)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Add-Content -LiteralPath $StepLog -Value ("$ " + $File + ' ' + ($Arguments -join ' ')) -Encoding UTF8
        if ($PSBoundParameters.ContainsKey('InputText')) {
            $output = $InputText | & $File @Arguments 2>&1
        } else {
            $output = & $File @Arguments 2>&1
        }
        $code = $LASTEXITCODE
        $lines = @($output | ForEach-Object { "$_" } | Where-Object { $_ -ne 'System.Management.Automation.RemoteException' })
        if ($lines.Count) { Add-Content -LiteralPath $StepLog -Value $lines -Encoding UTF8 }
        return [pscustomobject]@{ Code = $code; Lines = $lines; Text = ($lines -join "`n") }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Assert-Native($Result, [string]$What) {
    if ($Result.Code -ne 0) {
        $tail = ($Result.Lines | Select-Object -Last 8) -join ' | '
        throw "$What failed (exit $($Result.Code)): $tail"
    }
}

function Compose-Main([string[]]$Arguments, [string]$InputText) {
    $base = @('compose', '-p', $MainProject, '-f', 'compose.yaml', '-f', 'compose.demo.yaml')
    if ($PSBoundParameters.ContainsKey('InputText')) { return Invoke-Native -File 'docker' -Arguments ($base + $Arguments) -InputText $InputText }
    return Invoke-Native -File 'docker' -Arguments ($base + $Arguments)
}

function Compose-Restore([string[]]$Arguments, [string]$InputText) {
    if ($RestoreProject -eq $MainProject) { throw 'Restore project must differ from the main project.' }
    $base = @('compose', '-p', $RestoreProject, '-f', 'compose.yaml', '-f', 'compose.validation.yaml')
    if ($PSBoundParameters.ContainsKey('InputText')) { return Invoke-Native -File 'docker' -Arguments ($base + $Arguments) -InputText $InputText }
    return Invoke-Native -File 'docker' -Arguments ($base + $Arguments)
}

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    $started = Get-Date
    Write-Log ''
    Write-Log "==> $Name"
    $status = 'PASS'
    $detail = $null
    try {
        $detail = & $Body
        if ($detail -is [array]) { $detail = ($detail | ForEach-Object { "$_" }) -join '; ' }
    } catch {
        $status = 'FAIL'
        $detail = $_.Exception.Message
        Write-Log "    FAIL: $detail"
    }
    if ($status -eq 'PASS') { Write-Log "    PASS: $detail" }
    $script:Summary.steps += [ordered]@{ name = $Name; status = $status; seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1); detail = "$detail" }
    Save-Summary
    return ($status -eq 'PASS')
}

$CountSql = @"
SELECT table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from public.%I', table_name), false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name <> 'spatial_ref_sys'
ORDER BY table_name;
"@

function Get-TableCounts([string]$Which) {
    $psqlArgs = @('exec', '-T', 'postgres', 'psql', '-U', 'carbon', '-d', 'carbon', '-At', '-v', 'ON_ERROR_STOP=1')
    if ($Which -eq 'restore') { $result = Compose-Restore $psqlArgs $CountSql } else { $result = Compose-Main $psqlArgs $CountSql }
    Assert-Native $result "table count query ($Which)"
    $counts = [ordered]@{}
    foreach ($line in $result.Lines) {
        if ($line -match '^([A-Za-z0-9_]+)\|(\d+)$') { $counts[$Matches[1]] = [int64]$Matches[2] }
    }
    return $counts
}

function Read-CountFile([string]$Path) {
    $counts = [ordered]@{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([A-Za-z0-9_]+)\|(\d+)$') { $counts[$Matches[1]] = [int64]$Matches[2] }
    }
    return $counts
}

function Get-RawManifest {
    $raw = Join-Path $Root 'data\raw'
    $rows = @()
    if (Test-Path -LiteralPath $raw) {
        foreach ($file in Get-ChildItem -LiteralPath $raw -Recurse -File) {
            $relative = $file.FullName.Substring($raw.Length).TrimStart('\', '/').Replace('\', '/')
            $rows += [pscustomobject]@{ path = $relative; bytes = $file.Length; sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower() }
        }
    }
    return $rows
}

function Invoke-Backup([string]$Label) {
    $dir = Join-Path $Root "data\backups\$Stamp-$Label"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Assert-Native (Compose-Main @('up', '-d', '--wait', 'postgres')) 'postgres start'
    Assert-Native (Compose-Main @('exec', '-T', 'postgres', 'pg_dump', '-U', 'carbon', '-d', 'carbon', '-Fc', '-n', 'public', '-f', '/tmp/dss-backup.dump')) 'pg_dump'
    Assert-Native (Compose-Main @('cp', 'postgres:/tmp/dss-backup.dump', (Join-Path $dir 'db.dump'))) 'copy dump from container'
    Compose-Main @('exec', '-T', 'postgres', 'rm', '-f', '/tmp/dss-backup.dump') | Out-Null
    $counts = Get-TableCounts 'main'
    $countLines = @($counts.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" })
    Set-Content -LiteralPath (Join-Path $dir 'table-counts.tsv') -Value $countLines -Encoding UTF8
    $raw = Get-RawManifest
    $raw | Export-Csv -LiteralPath (Join-Path $dir 'raw-manifest.csv') -NoTypeInformation -Encoding UTF8
    $dumpHash = (Get-FileHash -LiteralPath (Join-Path $dir 'db.dump') -Algorithm SHA256).Hash.ToLower()
    $commit = $null
    try { $commit = (Invoke-Native -File 'git' -Arguments @('rev-parse', 'HEAD')).Lines | Select-Object -First 1 } catch { }
    $manifest = [ordered]@{
        created_at = (Get-Date).ToString('o'); label = $Label; git_commit = $commit
        dump = [ordered]@{ file = 'db.dump'; format = 'pg_dump custom, schema public'; sha256 = $dumpHash; bytes = (Get-Item -LiteralPath (Join-Path $dir 'db.dump')).Length }
        table_counts = $counts
        raw = [ordered]@{ files = $raw.Count; bytes = ($raw | Measure-Object -Property bytes -Sum).Sum }
        excluded = @('.env', '.secrets', 'data/cache', 'data/deployment', 'ollama models')
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $dir 'manifest.json') -Encoding UTF8
    $script:Summary.results["backup_$Label"] = [ordered]@{ dir = $dir; sha256 = $dumpHash; tables = $counts.Count; raw_files = $raw.Count }
    $script:LatestBackup = $dir
    return "$dir (tables=$($counts.Count), raw files=$($raw.Count))"
}

function Compare-Counts($Expected, $Actual) {
    $problems = @()
    foreach ($key in $Expected.Keys) {
        if (-not $Actual.Contains($key)) { $problems += "$key missing" }
        elseif ([int64]$Actual[$key] -ne [int64]$Expected[$key]) { $problems += "$key expected $($Expected[$key]) got $($Actual[$key])" }
    }
    return ,$problems
}

function Remove-RestoreProject {
    if ($RestoreProject -notmatch 'restoretest$') { throw 'Refusing to remove a non-test project.' }
    Compose-Restore @('down', '--remove-orphans') | Out-Null
    foreach ($volume in @("$($RestoreProject)_postgres_data", "$($RestoreProject)_redis_data")) {
        Invoke-Native -File 'docker' -Arguments @('volume', 'rm', '-f', $volume) | Out-Null
    }
}

function Invoke-WebCheck([string]$Url) {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 60
    return $response
}

function Invoke-VerifyRestore([string]$Dir) {
    if (-not $Dir) {
        $Dir = Get-ChildItem -LiteralPath (Join-Path $Root 'data\backups') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'db.dump') } | Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
    }
    if (-not $Dir) { throw 'No backup with db.dump found. Run -Action Backup first.' }
    $expected = Read-CountFile (Join-Path $Dir 'table-counts.tsv')
    Remove-RestoreProject
    Assert-Native (Compose-Restore @('up', '-d', '--wait', 'postgres', 'redis')) 'restore-test postgres start'
    Assert-Native (Compose-Restore @('exec', '-T', 'postgres', 'psql', '-U', 'carbon', '-d', 'carbon', '-v', 'ON_ERROR_STOP=1', '-c', 'CREATE EXTENSION IF NOT EXISTS postgis')) 'create postgis extension (restore-test)'
    Assert-Native (Compose-Restore @('cp', (Join-Path $Dir 'db.dump'), 'postgres:/tmp/restore.dump')) 'copy dump into restore-test'
    $restore = Compose-Restore @('exec', '-T', 'postgres', 'pg_restore', '-U', 'carbon', '-d', 'carbon', '--no-owner', '--no-privileges', '/tmp/restore.dump')
    Write-Log "    pg_restore exit $($restore.Code) (warnings such as 'schema public already exists' are expected)"
    $actual = Get-TableCounts 'restore'
    $problems = Compare-Counts $expected $actual
    $script:Summary.results.restore = [ordered]@{ backup = $Dir; tables = $expected.Count; mismatches = $problems; pg_restore_exit = $restore.Code }
    Save-Summary
    if ($problems.Count) { throw "Row count mismatch: $($problems -join '; ')" }
    return "restored $($expected.Count) tables with identical row counts from $Dir"
}

function Invoke-RestoreServices {
    Assert-Native (Compose-Restore @('up', '-d', '--build', '--wait', 'api', 'worker', 'frontend')) 'restore-test api/frontend start'
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/health' -TimeoutSec 60
    $ready = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/readiness' -TimeoutSec 120
    $map = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/map' -TimeoutSec 120
    $overlays = Invoke-RestMethod -Uri 'http://127.0.0.1:8010/api/map/overlays' -TimeoutSec 120
    $web = Invoke-WebCheck 'http://127.0.0.1:5190/map'
    $grids = @($map.grids.features).Count
    $script:Summary.results.restore_services = [ordered]@{ health = $health.status; postgis = $health.postgis; readiness_sources = $ready.summary.total_sources; grids = $grids; zoning_features = $overlays.meta.zoning_features; admin_features = $overlays.meta.admin_features; web_status = $web.StatusCode }
    Save-Summary
    if ($health.status -ne 'ok' -or $grids -lt 1 -or $web.StatusCode -ne 200) { throw 'restored services did not pass health/map/web checks' }
    return "health ok, grids=$grids, zoning=$($overlays.meta.zoning_features), admin=$($overlays.meta.admin_features), web=$($web.StatusCode)"
}

function Invoke-Pytest([string]$Which) {
    $stepLog = Join-Path $RunDir "pytest-$Which.log"
    $base = if ($Which -eq 'restore') { @('compose', '-p', $RestoreProject, '-f', 'compose.yaml', '-f', 'compose.validation.yaml') } else { @('compose', '-p', $MainProject, '-f', 'compose.yaml', '-f', 'compose.demo.yaml') }
    $result = Invoke-Native -File 'docker' -Arguments ($base + @('exec', '-T', 'api', 'python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider')) -StepLog $stepLog
    $last = ($result.Lines | Where-Object { $_ -match '(passed|failed|error)' } | Select-Object -Last 1)
    $script:Summary.results["pytest_$Which"] = [ordered]@{ exit = $result.Code; summary = $last; log = $stepLog }
    Save-Summary
    if ($result.Code -ne 0) { throw "pytest: $last" }
    return $last
}

function Invoke-E2E {
    $network = "$($RestoreProject)_default"
    $flag = Join-Path $Root 'data\offline.flag'
    $hadFlag = Test-Path -LiteralPath $flag
    $stepLog = Join-Path $RunDir 'e2e.log'
    $script = 'set -e; mkdir -p /tmp/e2e; cd /tmp/e2e; npm init -y >/dev/null; npm i --no-audit --no-fund --silent playwright@1.55.0; export NODE_PATH=/tmp/e2e/node_modules; timeout 600 node /work/scripts/e2e.cjs; timeout 300 node /work/scripts/e2e-overlays.cjs'
    try {
        $result = Invoke-Native -File 'docker' -Arguments @('run', '--rm', '--init', '--network', $network, '-e', 'DSS_URL=http://frontend', '-v', "$($Root):/work", $PlaywrightImage, 'bash', '-lc', $script) -StepLog $stepLog
    } finally {
        # e2e.cjs toggles offline mode through the shared data folder; restore the previous state.
        if (-not $hadFlag -and (Test-Path -LiteralPath $flag)) { Remove-Item -LiteralPath $flag -Force }
    }
    $script:Summary.results.e2e = [ordered]@{ exit = $result.Code; last = ($result.Lines | Select-Object -Last 3) -join ' | '; log = $stepLog }
    Save-Summary
    if ($result.Code -ne 0) { throw "E2E failed: $(($result.Lines | Select-Object -Last 3) -join ' | ')" }
    return ($result.Lines | Where-Object { $_ -match 'passed' } | Select-Object -Last 2) -join '; '
}

function Invoke-FrontendTest {
    $stepLog = Join-Path $RunDir 'frontend-test.log'
    $result = Invoke-Native -File 'docker' -Arguments @('build', '--progress=plain', '--target', 'test', '-t', 'carbon-urban-dss-frontend-test', 'frontend') -StepLog $stepLog
    $tests = ($result.Lines | Where-Object { $_ -match 'Tests\s+\d+' } | Select-Object -Last 1)
    $build = ($result.Lines | Where-Object { $_ -match 'built in|✓ built' } | Select-Object -Last 1)
    $script:Summary.results.frontend = [ordered]@{ exit = $result.Code; tests = $tests; build = $build; log = $stepLog }
    Save-Summary
    if ($result.Code -ne 0) { throw "frontend test/build failed (see $stepLog)" }
    return "$tests / $build"
}

function Invoke-Ops([string[]]$OpsArguments, [string]$OutName, [hashtable]$ExecEnv = @{}) {
    $out = "$ContainerRunDir/$OutName"
    $envArgs = @()
    foreach ($key in $ExecEnv.Keys) { $envArgs += @('-e', "$key=$($ExecEnv[$key])") }
    $result = Compose-Main (@('exec', '-T') + $envArgs + @('api', 'python', '-m', 'app.ops') + $OpsArguments + @('--out', $out))
    $file = Join-Path $RunDir $OutName
    if (-not (Test-Path -LiteralPath $file)) { Assert-Native $result "app.ops $($OpsArguments -join ' ')"; throw "missing $OutName" }
    return [pscustomobject]@{ Code = $result.Code; Json = (Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json); File = $file }
}

function Test-DockerEngine {
    $result = Invoke-Native -File 'docker' -Arguments @('info', '--format', '{{.ServerVersion}}')
    return ($result.Code -eq 0 -and ($result.Lines | Where-Object { $_ -match '^\d+\.' }))
}

function Start-DockerEngine {
    # Starts Docker Desktop when the engine is down and waits up to 4 minutes.
    if (Test-DockerEngine) { return 'already running' }
    $candidates = @()
    $cli = Get-Command docker -ErrorAction SilentlyContinue
    if ($cli) { $candidates += (Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $cli.Source))) 'Docker Desktop.exe') }
    $candidates += @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe", "$env:LOCALAPPDATA\Docker\Docker Desktop.exe")
    $desktop = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $desktop) { throw 'Docker Desktop executable not found. Start Docker Desktop manually and retry.' }
    Write-Log "    starting Docker Desktop: $desktop"
    Start-Process -FilePath $desktop | Out-Null
    for ($attempt = 0; $attempt -lt 48; $attempt++) {
        Start-Sleep -Seconds 5
        if (Test-DockerEngine) { return "started ($desktop)" }
    }
    throw 'Docker engine did not become ready within 4 minutes. Check Docker Desktop (disk location, WSL) and retry.'
}

function Invoke-Doctor {
    $checks = [ordered]@{}
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    $checks.docker_cli = [bool]$docker
    if (-not $docker) { throw 'Docker CLI not found. Install Docker Desktop (WSL2 backend).' }
    $checks.docker_start = Start-DockerEngine
    $info = Invoke-Native -File 'docker' -Arguments @('info', '--format', '{{.ServerVersion}}|{{.OperatingSystem}}|{{.MemTotal}}')
    $checks.docker_engine = if ($info.Code -eq 0) { $info.Lines | Select-Object -Last 1 } else { 'NOT RUNNING' }
    $compose = Invoke-Native -File 'docker' -Arguments @('compose', 'version', '--short')
    $checks.compose = if ($compose.Code -eq 0) { $compose.Lines | Select-Object -Last 1 } else { 'missing' }
    try {
        $settings = Join-Path $env:APPDATA 'Docker\settings-store.json'
        if (Test-Path -LiteralPath $settings) { $checks.docker_disk_dir = (Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json).CustomWslDistroDir }
    } catch { }
    try {
        $checks.free_gb = [ordered]@{}
        foreach ($drive in Get-PSDrive -PSProvider FileSystem) { if ($drive.Free) { $checks.free_gb[$drive.Name] = [math]::Round($drive.Free / 1GB, 1) } }
    } catch { }
    $envFile = Join-Path $Root '.env'
    $checks.env_file = Test-Path -LiteralPath $envFile
    $envStatus = [ordered]@{}
    if ($checks.env_file) {
        $values = @{}
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            if ($line -match '^\s*([A-Z0-9_]+)\s*=(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
        }
        foreach ($name in @('DATA_GO_KR_SERVICE_KEY', 'SGIS_CONSUMER_KEY', 'SGIS_CONSUMER_SECRET', 'VWORLD_API_KEY', 'VWORLD_DOMAIN')) {
            $value = $values[$name]
            if (-not $value) { $envStatus[$name] = 'missing' }
            elseif ($value -match '[^\x21-\x7E]') { $envStatus[$name] = 'invalid (non-ASCII or space: placeholder?)' }
            else { $envStatus[$name] = "set (length $($value.Length))" }
        }
    }
    $checks.env = $envStatus
    $ports = [ordered]@{}
    foreach ($port in @(5173, 8000, 5180, 8010, 5190)) {
        try { $ports["$port"] = [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) } catch { $ports["$port"] = 'unknown' }
    }
    $checks.listening_ports = $ports
    try {
        $git = Invoke-Native -File 'git' -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')
        $head = Invoke-Native -File 'git' -Arguments @('rev-parse', '--short', 'HEAD')
        $checks.git = "$($git.Lines | Select-Object -Last 1) @ $($head.Lines | Select-Object -Last 1)"
    } catch { $checks.git = 'git not installed' }
    $raw = Join-Path $Root 'data\raw'
    $checks.raw_files = if (Test-Path -LiteralPath $raw) { @(Get-ChildItem -LiteralPath $raw -Recurse -File).Count } else { 0 }
    $volumes = Invoke-Native -File 'docker' -Arguments @('volume', 'ls', '--format', '{{.Name}}')
    $checks.volumes = @($volumes.Lines | Where-Object { $_ -like "$MainProject*" })
    $script:Summary.results.doctor = $checks
    Save-Summary
    if ($checks.docker_engine -eq 'NOT RUNNING') { throw 'Docker engine is not running. Start Docker Desktop and retry.' }
    return "engine=$($checks.docker_engine); compose=$($checks.compose); raw files=$($checks.raw_files)"
}

function Invoke-Collect {
    $results = [ordered]@{}
    $vworldEnv = @{}
    if ($RetryRejected) {
        # The account owner fixed a key registration: forget cached rejections (successful responses stay cached).
        foreach ($provider in @('vworld', 'data_go_kr')) {
            $cleared = Invoke-Ops @('clear-rejections', $provider) "clear-rejections-$provider.json"
            Write-Log "    cleared $($cleared.Json.removed_rejections) cached rejection(s) for $provider"
        }
    }
    try {
        $probe = Invoke-Ops @('probe', 'vworld') 'probe-vworld-collect.json'
        $working = $probe.Json.working_domain
        if ($working -and $working -ne $probe.Json.configured_domain) {
            $vworldEnv = @{ VWORLD_DOMAIN = $working }
            $script:Summary.results.vworld_domain = [ordered]@{ configured = $probe.Json.configured_domain; working = $working; action = 'Set VWORLD_DOMAIN in .env to the working value' }
            Write-Log "    VWorld accepts domain '$working' (configured '$($probe.Json.configured_domain)'); using it for this run."
        } elseif (-not $working) {
            $script:Summary.results.vworld_domain = [ordered]@{ configured = $probe.Json.configured_domain; working = $null; action = 'Check the VWorld key service URL / API usage approval' }
        }
    } catch { Write-Log "    VWorld probe failed: $($_.Exception.Message)" }
    foreach ($dataset in @('sgis', 'vworld_zoning', 'vworld_cadastral', 'kapt_energy', 'kma_asos', 'energy')) {
        $execEnv = if ($dataset -like 'vworld_*') { $vworldEnv } else { @{} }
        $ops = Invoke-Ops @('staged', '--dataset', $dataset) "collect-$dataset.json" $execEnv
        $steps = @($ops.Json.steps)
        $last = $steps | Select-Object -Last 1
        $message = if ($last.blockers) { ($last.blockers | ForEach-Object { $_.message }) -join ' / ' } elseif ($last.errors) { ($last.errors | ForEach-Object { $_.message }) -join ' / ' } else { $last.source.quality }
        $results[$dataset] = [ordered]@{ final = $ops.Json.final_status; reached = $ops.Json.reached_scope; message = $message }
        Write-Log "    $dataset -> $($ops.Json.final_status) @ $($ops.Json.reached_scope): $message"
    }
    $script:Summary.results.collect = $results
    Save-Summary
    return (($results.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value.final)" }) -join ', ')
}

function Invoke-ExportBundle {
    Invoke-Backup 'bundle' | Out-Null
    $source = $script:LatestBackup
    $stage = Join-Path $RunDir 'bundle'
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    foreach ($name in @('db.dump', 'table-counts.tsv', 'raw-manifest.csv', 'manifest.json')) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination $stage }
    $raw = Join-Path $Root 'data\raw'
    if (Test-Path -LiteralPath $raw) { Compress-Archive -Path (Join-Path $raw '*') -DestinationPath (Join-Path $stage 'raw.zip') -CompressionLevel Optimal }
    if ($IncludeUploads -and (Test-Path -LiteralPath (Join-Path $Root 'data\uploads'))) { Compress-Archive -Path (Join-Path $Root 'data\uploads\*') -DestinationPath (Join-Path $stage 'uploads.zip') }
    @(
        'Carbon Urban DSS data bundle',
        'Import on a new PC (after git clone and Docker Desktop start):',
        '  scripts\dss.cmd ImportBundle -BundlePath <this zip>',
        'Contains: PostgreSQL dump (schema public), table row counts, data/raw archive, SHA-256 checksums.',
        'Does NOT contain: .env / API keys, .secrets, data/cache, data/deployment, Ollama models.',
        'Share only with approved team members and follow each provider''s terms of use.'
    ) | Set-Content -LiteralPath (Join-Path $stage 'README-IMPORT.txt') -Encoding UTF8
    $sums = Get-ChildItem -LiteralPath $stage -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" }
    Set-Content -LiteralPath (Join-Path $stage 'SHA256SUMS.txt') -Value $sums -Encoding ASCII
    $bundleDir = Join-Path $Root 'data\backups\bundles'
    New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
    $zip = Join-Path $bundleDir "carbon-dss-bundle-$Stamp.zip"
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
    Set-Content -LiteralPath "$zip.sha256" -Value "$hash  $(Split-Path -Leaf $zip)" -Encoding ASCII
    $script:Summary.results.bundle = [ordered]@{ zip = $zip; sha256 = $hash; bytes = (Get-Item -LiteralPath $zip).Length }
    Remove-Item -LiteralPath $stage -Recurse -Force
    return "$zip ($([math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)) MB)"
}

function Invoke-ImportBundle {
    if (-not $BundlePath -or -not (Test-Path -LiteralPath $BundlePath)) { throw 'Use -BundlePath <carbon-dss-bundle-*.zip>' }
    $stage = Join-Path $RunDir 'bundle'
    Expand-Archive -LiteralPath $BundlePath -DestinationPath $stage -Force
    foreach ($line in Get-Content -LiteralPath (Join-Path $stage 'SHA256SUMS.txt')) {
        if ($line -match '^([0-9a-f]{64})\s+(.+)$') {
            $actual = (Get-FileHash -LiteralPath (Join-Path $stage $Matches[2]) -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $Matches[1]) { throw "Checksum mismatch: $($Matches[2])" }
        }
    }
    Write-Log '    checksums OK'
    Assert-Native (Compose-Main @('up', '-d', '--wait', 'postgres', 'redis')) 'postgres start'
    $existing = Get-TableCounts 'main'
    $nonEmpty = @($existing.GetEnumerator() | Where-Object { $_.Value -gt 0 })
    if ($existing.Count -gt 0) { throw "Target database already has $($existing.Count) tables ($($nonEmpty.Count) non-empty). Import only into an empty database; back it up and use a new PC/volume instead." }
    $conflicts = @()
    if (Test-Path -LiteralPath (Join-Path $stage 'raw.zip')) {
        $rawStage = Join-Path $stage 'raw'
        Expand-Archive -LiteralPath (Join-Path $stage 'raw.zip') -DestinationPath $rawStage -Force
        $rawTarget = Join-Path $Root 'data\raw'
        foreach ($file in Get-ChildItem -LiteralPath $rawStage -Recurse -File) {
            $relative = $file.FullName.Substring($rawStage.Length).TrimStart('\', '/')
            $target = Join-Path $rawTarget $relative
            if (Test-Path -LiteralPath $target) {
                if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) { $conflicts += $relative }
                continue
            }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $target
        }
    }
    Assert-Native (Compose-Main @('exec', '-T', 'postgres', 'psql', '-U', 'carbon', '-d', 'carbon', '-v', 'ON_ERROR_STOP=1', '-c', 'CREATE EXTENSION IF NOT EXISTS postgis')) 'create postgis extension'
    Assert-Native (Compose-Main @('cp', (Join-Path $stage 'db.dump'), 'postgres:/tmp/restore.dump')) 'copy dump'
    $restore = Compose-Main @('exec', '-T', 'postgres', 'pg_restore', '-U', 'carbon', '-d', 'carbon', '--no-owner', '--no-privileges', '/tmp/restore.dump')
    Write-Log "    pg_restore exit $($restore.Code)"
    $problems = Compare-Counts (Read-CountFile (Join-Path $stage 'table-counts.tsv')) (Get-TableCounts 'main')
    $script:Summary.results.import = [ordered]@{ bundle = $BundlePath; raw_conflicts_kept_local = $conflicts; mismatches = $problems }
    Save-Summary
    if ($problems.Count) { throw "Row count mismatch after import: $($problems -join '; ')" }
    Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'api', 'worker', 'frontend')) 'service start'
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 60
    Remove-Item -LiteralPath $stage -Recurse -Force
    return "imported; health=$($health.status); raw conflicts kept local: $($conflicts.Count)"
}

# ----------------------------------------------------------------------------
$ok = $true
$selected = $Action
if ($Action -notin @('Doctor', 'All')) {
    if (-not (Invoke-Step 'Docker engine' { Start-DockerEngine })) { $selected = 'Skip'; $ok = $false }
}
if ($selected -in @('Status', 'Probe', 'Collect')) {
    # app.ops runs inside the api image; make sure it contains the current code first.
    if (-not (Invoke-Step 'Services up to date' { Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'postgres', 'redis', 'api', 'worker')) 'compose up --build'; 'api/worker current' })) { $selected = 'Skip'; $ok = $false }
}
switch ($selected) {
    'Doctor' { $ok = Invoke-Step 'Doctor' { Invoke-Doctor } }
    'Status' { $ok = Invoke-Step 'Status' { $s = Invoke-Ops @('status') 'status.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count), raw=$($s.Json.raw.files)" } }
    'Backup' { $ok = Invoke-Step 'Backup' { Invoke-Backup 'manual' } }
    'Rebuild' { $ok = Invoke-Step 'Rebuild services' { Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'postgres', 'redis', 'api', 'worker', 'frontend')) 'compose up --build'; 'api/worker/frontend rebuilt' } }
    'Probe' {
        $ok = Invoke-Step 'Probe SGIS' { $p = Invoke-Ops @('probe', 'sgis') 'probe-sgis.json'; ($p.Json.steps | ForEach-Object { "$($_.step):$($_.errCd)$($_.ok)" }) -join ' ' }
        $ok = (Invoke-Step 'Probe VWorld' { $p = Invoke-Ops @('probe', 'vworld') 'probe-vworld.json'; "working_domain=$($p.Json.working_domain); " + (($p.Json.steps | ForEach-Object { "$($_.step)[$($_.domain)]:$($_.status) $($_.error.code) features=$($_.features)" }) -join ' ') }) -and $ok
    }
    'Collect' { $ok = Invoke-Step 'Staged collection' { Invoke-Collect } }
    'VerifyRestore' {
        $ok = Invoke-Step 'Restore into separate project' { Invoke-VerifyRestore $BackupDir }
        if ($ok) {
            $ok = (Invoke-Step 'Restored services (health/map/web)' { Invoke-RestoreServices }) -and $ok
            $ok = (Invoke-Step 'pytest (restored copy)' { Invoke-Pytest 'restore' }) -and $ok
            if (-not $SkipE2E) { $ok = (Invoke-Step 'Browser E2E (restored copy)' { Invoke-E2E }) -and $ok }
        }
        if (-not $KeepRestoreProject) { Invoke-Step 'Remove restore-test project' { Remove-RestoreProject; 'removed' } | Out-Null }
    }
    'FrontendTest' { $ok = Invoke-Step 'Frontend Vitest + build' { Invoke-FrontendTest } }
    'E2E' { $ok = Invoke-Step 'Browser E2E (restore-test project must be running)' { Invoke-E2E } }
    'ExportBundle' { $ok = Invoke-Step 'Export team bundle' { Invoke-ExportBundle } }
    'ImportBundle' { $ok = Invoke-Step 'Import team bundle' { Invoke-ImportBundle } }
    'All' {
        $ok = Invoke-Step 'Doctor' { Invoke-Doctor }
        if ($ok) {
            $ok = Invoke-Step 'Backup before changes' { Invoke-Backup 'before' }
            if ($ok) {
                $ok = Invoke-Step 'Rebuild services' { Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'postgres', 'redis', 'api', 'worker', 'frontend')) 'compose up --build'; 'api/worker/frontend rebuilt' }
            }
            if ($ok) {
                Invoke-Step 'Status before collection' { $s = Invoke-Ops @('status') 'status-before.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count), raw=$($s.Json.raw.files)" } | Out-Null
                Invoke-Step 'Probe SGIS' { $p = Invoke-Ops @('probe', 'sgis') 'probe-sgis.json'; ($p.Json.steps | ForEach-Object { "$($_.step):$($_.errCd)$($_.ok)" }) -join ' ' } | Out-Null
                Invoke-Step 'Probe VWorld' { $p = Invoke-Ops @('probe', 'vworld') 'probe-vworld.json'; "working_domain=$($p.Json.working_domain); " + (($p.Json.steps | ForEach-Object { "$($_.step)[$($_.domain)]:$($_.status) $($_.error.code) features=$($_.features)" }) -join ' ') } | Out-Null
                if (-not $SkipCollect) { Invoke-Step 'Staged collection' { Invoke-Collect } | Out-Null }
                Invoke-Step 'Status after collection' { $s = Invoke-Ops @('status') 'status-after.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count), raw=$($s.Json.raw.files)" } | Out-Null
                $backupOk = Invoke-Step 'Backup after collection' { Invoke-Backup 'after' }
                if ($backupOk) {
                    $restored = Invoke-Step 'Restore into separate project' { Invoke-VerifyRestore $script:LatestBackup }
                    if ($restored) {
                        Invoke-Step 'Restored services (health/map/web)' { Invoke-RestoreServices } | Out-Null
                        Invoke-Step 'pytest (restored copy)' { Invoke-Pytest 'restore' } | Out-Null
                        if (-not $SkipE2E) { Invoke-Step 'Browser E2E (restored copy)' { Invoke-E2E } | Out-Null }
                    }
                    if (-not $KeepRestoreProject) { Invoke-Step 'Remove restore-test project' { Remove-RestoreProject; 'removed' } | Out-Null }
                }
                Invoke-Step 'Frontend Vitest + build' { Invoke-FrontendTest } | Out-Null
            }
        }
        $ok = -not ($Summary.steps | Where-Object { $_.status -eq 'FAIL' })
    }
}

$Summary.finished_at = (Get-Date).ToString('o')
$Summary.ok = [bool]$ok
Save-Summary
Write-Log ''
Write-Log '================ SUMMARY ================'
foreach ($step in $Summary.steps) { Write-Log ("[{0}] {1} ({2}s) {3}" -f $step.status, $step.name, $step.seconds, $step.detail) }
Write-Log "Results: $RunDir"
if (-not $ok) { exit 1 }
