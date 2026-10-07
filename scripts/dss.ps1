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
                -Datasets kapt_energy,energy: collect only these datasets
                -SkipHeavy: keep the parcel layer (vworld_cadastral) at LIMITED
                Full K-apt / 건축HUB / building collection can take 1-2 hours; every
                successful response is cached, so an interrupted run resumes.
  CollectHistory  collect everything still missing (-FromYear 2015 -ToYear 2025, optional -Datasets):
  CollectAll      (same) SGIS, ASOS, K-apt and 건축HUB energy per year, then VWorld zoning,
                buildings, all parcels and the 건축물대장 표제부. Items already in the DB
                and datasets without a working key are skipped without any request.
                Daily API quotas can stop it; run the same command again the next day
                and it resumes (data/ops/history-progress.json, cached responses).
  Snapshot      save the main API responses (map, dashboard, overlays, readiness,
                collections) as JSON in the run folder for offline UI review
  VerifyRestore restore the latest backup into a separate throwaway project,
                compare every table count, run pytest and (optionally) browser E2E
  FrontendTest  Vitest + production build inside Linux (docker build --target test)
  ExportBundle  team share bundle: DB dump + data/raw (+uploads) + checksums + the simulation
                cases recorded on this DB (simulation_cases.json). -OutDir puts the bundle
                (and its staging files) on another drive when C: is short of space
  ImportBundle  import a bundle into an EMPTY database on a new PC (-BundlePath); then the
                bundle's simulation cases are re-computed here and must match
  VerifyCases   re-compute the fixed simulation cases and compare with the recorded values
                (-CasesPath <simulation_cases.json>; default: the file in backend/cases)
  MergeBundle   add a teammate's bundle to THIS database without duplicates (-BundlePath,
                -DryRun to only count): backup first, rows matched on natural keys, existing
                rows never changed, new raw files copied, report in merge.json
  VerifyBundle  new-PC simulation: export a bundle, 'git clone' HEAD into a clean
                folder, import there into a separate project, compare counts,
                check API/web and the simulation cases, then remove that project
                (-OutDir: bundle and clean clone on another drive, clone removed afterwards)
  All           Doctor, Backup, Rebuild, Status, Probe, Collect, Status, Backup,
                VerifyRestore(+pytest,+E2E), FrontendTest, VerifyBundle

Safety
  * The main project's volumes are never removed. Only the throwaway project
    'carbon-urban-dss-restoretest' is cleaned up after verification.
  * .env, .secrets, data/cache, data/deployment and Ollama models are never
    copied into backups or bundles.
  * Results are written to data/ops/<timestamp>-<action>/ (summary.json, *.log).
#>
param(
    [ValidateSet('All', 'Doctor', 'Status', 'Backup', 'Rebuild', 'Probe', 'Collect', 'CollectHistory', 'CollectAll', 'Snapshot', 'VerifyRestore', 'FrontendTest', 'E2E', 'ExportBundle', 'ImportBundle', 'MergeBundle', 'VerifyBundle', 'VerifyCases')]
    [string]$Action = 'All',
    [string]$BundlePath,
    [string]$OutDir,
    [string]$CasesPath,
    [string]$BackupDir,
    [switch]$IncludeUploads,
    [switch]$DryRun,
    [switch]$SkipE2E,
    [switch]$SkipCollect,
    [switch]$KeepRestoreProject,
    [switch]$RetryRejected,
    [string[]]$Datasets,
    [switch]$SkipHeavy,
    [int]$FromYear = 2015,
    [int]$ToYear = 2025
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
$MainProject = if ($env:DSS_PROJECT) { $env:DSS_PROJECT } else { 'carbon-urban-dss' }
$MainOverride = if ($env:DSS_COMPOSE_OVERRIDE) { $env:DSS_COMPOSE_OVERRIDE } else { 'compose.demo.yaml' }
$ApiPort = if ($env:DSS_API_PORT) { $env:DSS_API_PORT } else { '8000' }
$WebPort = if ($env:DSS_WEB_PORT) { $env:DSS_WEB_PORT } else { '5173' }
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
    $base = @('compose', '-p', $MainProject, '-f', 'compose.yaml', '-f', $MainOverride)
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

function Wait-Postgres([string]$Which) {
    # The postgres image initialises a new volume with a temporary server that listens only on the
    # Unix socket, then restarts. 'compose up --wait' can pass during that phase, so wait until the
    # final server accepts TCP connections inside the container.
    # No embedded double quotes: Windows PowerShell 5.1 does not escape them for native commands.
    $probe = @('exec', '-T', 'postgres', 'sh', '-c', 'PGPASSWORD=$POSTGRES_PASSWORD psql -h 127.0.0.1 -U ${POSTGRES_USER:-carbon} -d ${POSTGRES_DB:-carbon} -Atc ''select 1''')
    # A fresh volume on a busy PC measured 3+ minutes (initdb, 2026-09-27), so allow up to 5 minutes.
    for ($attempt = 0; $attempt -lt 150; $attempt++) {
        $result = if ($Which -eq 'restore') { Compose-Restore $probe } else { Compose-Main $probe }
        if ($result.Code -eq 0 -and ($result.Lines -contains '1')) { return }
        Start-Sleep -Seconds 2
    }
    throw "postgres ($Which) did not accept TCP connections within 300 s"
}

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
    # A list, not $rows += (that copies the whole array per file; data/raw has tens of thousands of files).
    $rows = [System.Collections.Generic.List[object]]::new()
    if (Test-Path -LiteralPath $raw) {
        foreach ($file in Get-ChildItem -LiteralPath $raw -Recurse -File) {
            $relative = $file.FullName.Substring($raw.Length).TrimStart('\', '/').Replace('\', '/')
            $rows.Add([pscustomobject]@{ path = $relative; bytes = $file.Length; sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower() })
        }
    }
    return ,$rows.ToArray()
}

function Invoke-Backup([string]$Label) {
    $dir = Join-Path $Root "data\backups\$Stamp-$Label"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Assert-Native (Compose-Main @('up', '-d', '--wait', 'postgres')) 'postgres start'
    # Counts before and after the dump: a collection may be writing meanwhile (the dump itself is one
    # consistent snapshot, the counts are not), so a restore is checked against that range.
    $before = Get-TableCounts 'main'
    Assert-Native (Compose-Main @('exec', '-T', 'postgres', 'pg_dump', '-U', 'carbon', '-d', 'carbon', '-Fc', '-n', 'public', '-f', '/tmp/dss-backup.dump')) 'pg_dump'
    Assert-Native (Compose-Main @('cp', 'postgres:/tmp/dss-backup.dump', (Join-Path $dir 'db.dump'))) 'copy dump from container'
    Compose-Main @('exec', '-T', 'postgres', 'rm', '-f', '/tmp/dss-backup.dump') | Out-Null
    $counts = Get-TableCounts 'main'
    $countLines = @($counts.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" })
    Set-Content -LiteralPath (Join-Path $dir 'table-counts.tsv') -Value $countLines -Encoding UTF8
    $changing = @($counts.Keys | Where-Object { -not $before.Contains($_) -or [int64]$before[$_] -ne [int64]$counts[$_] })
    if ($changing.Count) {
        Set-Content -LiteralPath (Join-Path $dir 'table-counts-before.tsv') -Value @($before.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" }) -Encoding UTF8
    }
    $raw = Get-RawManifest
    $raw | Export-Csv -LiteralPath (Join-Path $dir 'raw-manifest.csv') -NoTypeInformation -Encoding UTF8
    $dumpHash = (Get-FileHash -LiteralPath (Join-Path $dir 'db.dump') -Algorithm SHA256).Hash.ToLower()
    $commit = $null
    try { $commit = (Invoke-Native -File 'git' -Arguments @('rev-parse', 'HEAD')).Lines | Select-Object -First 1 } catch { }
    $manifest = [ordered]@{
        created_at = (Get-Date).ToString('o'); label = $Label; git_commit = $commit
        dump = [ordered]@{ file = 'db.dump'; format = 'pg_dump custom, schema public'; sha256 = $dumpHash; bytes = (Get-Item -LiteralPath (Join-Path $dir 'db.dump')).Length }
        table_counts = $counts
        tables_written_during_backup = $changing
        raw = [ordered]@{ files = $raw.Count; bytes = ($raw | Measure-Object -Property bytes -Sum).Sum }
        excluded = @('.env', '.secrets', 'data/cache', 'data/deployment', 'ollama models')
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $dir 'manifest.json') -Encoding UTF8
    $script:Summary.results["backup_$Label"] = [ordered]@{ dir = $dir; sha256 = $dumpHash; tables = $counts.Count; raw_files = $raw.Count }
    $script:LatestBackup = $dir
    return "$dir (tables=$($counts.Count), raw files=$($raw.Count))"
}

function Compare-Counts($Expected, $Actual, $Before = $null) {
    # $Before: counts taken just before the dump. A table written during the backup must restore
    # to a count between the two; every other table must match exactly.
    $problems = @()
    foreach ($key in $Expected.Keys) {
        if (-not $Actual.Contains($key)) { $problems += "$key missing"; continue }
        $got = [int64]$Actual[$key]; $want = [int64]$Expected[$key]
        if ($Before -and $Before.Contains($key) -and [int64]$Before[$key] -ne $want) {
            $lo = [Math]::Min([int64]$Before[$key], $want); $hi = [Math]::Max([int64]$Before[$key], $want)
            if ($got -lt $lo -or $got -gt $hi) { $problems += "$key expected $lo..$hi got $got" }
        }
        elseif ($got -ne $want) { $problems += "$key expected $want got $got" }
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
    $beforeFile = Join-Path $Dir 'table-counts-before.tsv'
    $beforeCounts = if (Test-Path -LiteralPath $beforeFile) { Read-CountFile $beforeFile } else { $null }
    Remove-RestoreProject
    Assert-Native (Compose-Restore @('up', '-d', '--wait', 'postgres', 'redis')) 'restore-test postgres start'
    Wait-Postgres 'restore'
    Assert-Native (Compose-Restore @('exec', '-T', 'postgres', 'psql', '-U', 'carbon', '-d', 'carbon', '-v', 'ON_ERROR_STOP=1', '-c', 'CREATE EXTENSION IF NOT EXISTS postgis')) 'create postgis extension (restore-test)'
    Assert-Native (Compose-Restore @('cp', (Join-Path $Dir 'db.dump'), 'postgres:/tmp/restore.dump')) 'copy dump into restore-test'
    $restore = Compose-Restore @('exec', '-T', 'postgres', 'pg_restore', '-U', 'carbon', '-d', 'carbon', '--no-owner', '--no-privileges', '/tmp/restore.dump')
    Write-Log "    pg_restore exit $($restore.Code) (warnings such as 'schema public already exists' are expected)"
    $actual = Get-TableCounts 'restore'
    $problems = Compare-Counts $expected $actual $beforeCounts
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
    $base = if ($Which -eq 'restore') { @('compose', '-p', $RestoreProject, '-f', 'compose.yaml', '-f', 'compose.validation.yaml') } else { @('compose', '-p', $MainProject, '-f', 'compose.yaml', '-f', $MainOverride) }
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
    if (-not $tests -and ($result.Text -match 'RUN npm test\s*\n[^\n]*CACHED')) { $tests = 'CACHED: frontend sources unchanged since the last passing Vitest run' }
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
    try {
        $dg = Invoke-Ops @('probe', 'datagokr') 'probe-datagokr-collect.json'
        foreach ($step in @($dg.Json.steps)) { Write-Log "    data.go.kr $($step.step): http=$($step.http) code=$($step.result_code) items=$($step.items) $($step.result_msg)" }
    } catch { Write-Log "    data.go.kr probe failed: $($_.Exception.Message)" }
    # Cheap sources first, then the official building layer (map), then the long energy runs.
    # Every successful response is cached, so an interrupted run resumes where it stopped.
    $order = @('sgis', 'vworld_zoning', 'vworld_buildings', 'kma_asos', 'kapt_energy', 'energy', 'vworld_cadastral')
    if ($Datasets) { $wanted = @($Datasets | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ }); $order = @($order | Where-Object { $wanted -contains $_ }) }
    $estimates = @{ vworld_buildings = '~10-20 min (916 grids, paged)'; kapt_energy = '~40-60 min (364 complexes x 12 months)'; energy = '~40-70 min (200+ household complexes x 12 months x 2)'; vworld_cadastral = '~20-40 min (all parcels)' }
    foreach ($dataset in $order) {
        $execEnv = if ($dataset -like 'vworld_*') { $vworldEnv.Clone() } else { @{} }
        if ($dataset -eq 'vworld_cadastral' -and -not $SkipHeavy) { $execEnv['VWORLD_CADASTRAL_FULL'] = 'true' }
        if ($estimates.ContainsKey($dataset)) { Write-Log "    ${dataset}: $($estimates[$dataset]); progress is shown in the web 'Data' page (collection jobs)" }
        $maxScope = if ($dataset -eq 'vworld_cadastral' -and $SkipHeavy) { @('--max-scope', 'limited') } else { @() }
        $ops = Invoke-Ops (@('staged', '--dataset', $dataset) + $maxScope) "collect-$dataset.json" $execEnv
        $steps = @($ops.Json.steps)
        $last = $steps | Select-Object -Last 1
        $message = if ($last.blockers) { ($last.blockers | ForEach-Object { $_.message }) -join ' / ' } elseif ($last.errors) { ($last.errors | ForEach-Object { $_.message }) -join ' / ' } else { $last.source.quality }
        $results[$dataset] = [ordered]@{ final = $ops.Json.final_status; reached = $ops.Json.reached_scope; message = $message }
        Write-Log "    $dataset -> $($ops.Json.final_status) @ $($ops.Json.reached_scope): $message"
    }
    $script:Summary.results.collect = $results
    try {
        $models = Invoke-Ops @('models') 'models.json'
        $script:Summary.results.models = [ordered]@{ status = $models.Json.status; models = @($models.Json.models | ForEach-Object { "$($_.energy_type): $($_.status) obs=$($_.observations) grids=$($_.grid_count) blocks=$($_.spatial_blocks) months=$($_.months)" }) }
        Write-Log "    model validation: $($models.Json.status)"
    } catch { Write-Log "    model validation failed: $($_.Exception.Message)" }
    Save-Summary
    return (($results.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value.final)" }) -join ', ')
}

function Invoke-CollectHistory {
    # Streams progress to the console and the run log: the back-fill can run for hours.
    $cliArgs = @('exec', '-T', 'api', 'python', '-u', '-m', 'app.cli', 'collect-history', '--from', "$FromYear", '--to', "$ToYear")
    if ($Datasets) { $cliArgs += @('--datasets', ((@($Datasets | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })) -join ',')) }
    $historyLog = Join-Path $RunDir 'collect-history.log'
    Write-Log "    back-fill $FromYear-$ToYear. K-apt/건축HUB energy can hit the daily quota; run the same command again the next day to resume."
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker compose -p $MainProject -f compose.yaml -f $MainOverride @cliArgs 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -ne 'System.Management.Automation.RemoteException' } | ForEach-Object { Add-Content -LiteralPath $historyLog -Value $_ -Encoding UTF8; Write-Host "    $_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "collect-history exited $code (see collect-history.log)" }
    $last = Get-Content -LiteralPath $historyLog -Encoding UTF8 | Where-Object { $_ -match '^\{"statuses"' } | Select-Object -Last 1
    $script:Summary.results.collect_history = "$last"
    return "history ${FromYear}-${ToYear}: $last"
}

function Invoke-Snapshot([string]$Base = "http://127.0.0.1:$ApiPort") {
    # Raw API responses (UTF-8 bytes written as-is) for offline UI review; no credentials are involved.
    $dir = Join-Path $RunDir 'api'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $saved = @()
    foreach ($item in @(@('map', '/api/map?year=2025'), @('dashboard', '/api/dashboard?year=2025'), @('overlays', '/api/map/overlays?year=2025'), @('readiness', '/api/readiness'), @('collections', '/api/collections'), @('sources', '/api/sources?year=2025'), @('model', '/api/model?year=2025'), @('system', '/api/system'))) {
        $target = Join-Path $dir "$($item[0]).json"
        Invoke-WebRequest -Uri ($Base + $item[1]) -OutFile $target -UseBasicParsing -TimeoutSec 180
        $saved += "$($item[0])=$([math]::Round((Get-Item -LiteralPath $target).Length / 1KB))KB"
    }
    $map = Get-Content -LiteralPath (Join-Path $dir 'map.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $grid = $map.selected_sector.grid_id
    if ($map.buildings_mode -eq 'viewport' -and $grid) {
        $lon = [double]$map.center[0]; $lat = [double]$map.center[1]
        $box = '{0},{1},{2},{3}' -f ($lon - 0.03).ToString([Globalization.CultureInfo]::InvariantCulture), ($lat - 0.03).ToString([Globalization.CultureInfo]::InvariantCulture), ($lon + 0.03).ToString([Globalization.CultureInfo]::InvariantCulture), ($lat + 0.03).ToString([Globalization.CultureInfo]::InvariantCulture)
        Invoke-WebRequest -Uri "$Base/api/map/buildings?bbox=$box" -OutFile (Join-Path $dir 'buildings-center.json') -UseBasicParsing -TimeoutSec 180
        $saved += 'buildings-center'
    }
    return ($saved -join ', ')
}

function New-ZipFromFolder([string]$Folder, [string]$ZipPath, [string]$Level = 'Optimal') {
    # Streams each file into the zip (UTF-8 names, Zip64 when needed). Compress-Archive in Windows
    # PowerShell 5.1 keeps entries in memory and cannot store files over 2 GB, so it is not used for bundles.
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Folder, $ZipPath, [System.IO.Compression.CompressionLevel]$Level, $false)
}

function Expand-ZipToFolder([string]$ZipPath, [string]$Folder) {
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $Folder) { Remove-Item -LiteralPath $Folder -Recurse -Force }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Folder)
}

function Invoke-CaseCheck([string]$File) {
    # Fixed simulation cases (backend/cases/simulation_cases.json or the copy inside a bundle) computed on this DB and
    # compared with the recorded values. Reads only: no scenario or report is saved.
    $cliArgs = @('exec', '-T', '-e', 'PYTHONIOENCODING=utf-8', 'api', 'python', '-m', 'app.cli', 'verify-cases', '--out', "$ContainerRunDir/cases-check.json")
    if ($File) {
        if (-not (Test-Path -LiteralPath $File)) { throw "cases file not found: $File" }
        $copy = Join-Path $RunDir 'simulation_cases.json'
        if ((Resolve-Path -LiteralPath $File).Path -ne $copy) { Copy-Item -LiteralPath $File -Destination $copy -Force }
        $cliArgs += @('--cases', "$ContainerRunDir/simulation_cases.json")
    }
    $result = Compose-Main $cliArgs
    $report = Join-Path $RunDir 'cases-check.json'
    if (-not (Test-Path -LiteralPath $report)) { Assert-Native $result 'verify-cases'; throw 'cases-check.json missing (rebuild api)' }
    $json = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
    $c = $json.counts
    $total = $c.MATCH + $c.DIFF + $c.ERROR + $c.NOT_RECORDED
    $script:Summary.results.cases = [ordered]@{ recorded_on = $json.cases_recorded_on; match = $c.MATCH; diff = $c.DIFF; error = $c.ERROR; not_recorded = $c.NOT_RECORDED; report = $report }
    Save-Summary
    $text = "simulation cases: $($c.MATCH)/$total match (recorded $($json.cases_recorded_on))"
    if (-not $json.all_match) {
        $bad = @($json.results | Where-Object { $_.status -ne 'MATCH' } | ForEach-Object { "$($_.id) $($_.status)" })
        throw "$text; not matching: $($bad -join ', ') (details: $report)"
    }
    return $text
}

function Invoke-ExportBundle {
    Invoke-Backup 'bundle' | Out-Null
    $source = $script:LatestBackup
    # Same DB state as the dump: the cases computed now travel with the bundle and are re-checked on import.
    $recorded = Compose-Main @('exec', '-T', '-e', 'PYTHONIOENCODING=utf-8', 'api', 'python', '-m', 'app.cli', 'verify-cases', '--record', "$ContainerRunDir/simulation_cases.json", '--note', "carbon-dss-bundle-$Stamp")
    $bundleDir = if ($OutDir) { $OutDir } else { Join-Path $Root 'data\backups\bundles' }
    New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
    $stage = if ($OutDir) { Join-Path $OutDir "stage-$Stamp" } else { Join-Path $RunDir 'bundle' }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    foreach ($name in @('db.dump', 'table-counts.tsv', 'raw-manifest.csv', 'manifest.json')) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination $stage }
    if (Export-CollectionProgress (Join-Path $stage 'collection-progress.json')) { Write-Log '    collection progress recorded into the bundle' }
    $casesFile = Join-Path $RunDir 'simulation_cases.json'
    if (Test-Path -LiteralPath $casesFile) { Copy-Item -LiteralPath $casesFile -Destination $stage; Write-Log '    simulation cases recorded into the bundle' }
    else { Write-Log "    note: simulation cases not recorded (exit $($recorded.Code); rebuild api to include them)" }
    $raw = Join-Path $Root 'data\raw'
    if (Test-Path -LiteralPath $raw) { New-ZipFromFolder $raw (Join-Path $stage 'raw.zip') }
    if ($IncludeUploads -and (Test-Path -LiteralPath (Join-Path $Root 'data\uploads'))) { New-ZipFromFolder (Join-Path $Root 'data\uploads') (Join-Path $stage 'uploads.zip') }
    @(
        'Carbon Urban DSS data bundle',
        'Import on a new PC (after git clone and Docker Desktop start):',
        '  scripts\dss.cmd ImportBundle -BundlePath <this zip>',
        'Contains: PostgreSQL dump (schema public), table row counts, data/raw archive, SHA-256 checksums,',
        '          simulation_cases.json (fixed simulation cases computed on this data; ImportBundle re-checks them),',
        '          collection-progress.json (which collection years are finished; ImportBundle restores it).',
        'Does NOT contain: .env / API keys, .secrets, data/cache, data/deployment, Ollama models.',
        'Share only with approved team members and follow each provider''s terms of use.'
    ) | Set-Content -LiteralPath (Join-Path $stage 'README-IMPORT.txt') -Encoding UTF8
    $sums = Get-ChildItem -LiteralPath $stage -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" }
    Set-Content -LiteralPath (Join-Path $stage 'SHA256SUMS.txt') -Value $sums -Encoding ASCII
    $zip = Join-Path $bundleDir "carbon-dss-bundle-$Stamp.zip"
    # db.dump (pg_dump -Fc) and raw.zip are already compressed: store them as they are.
    New-ZipFromFolder $stage $zip 'NoCompression'
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
    Set-Content -LiteralPath "$zip.sha256" -Value "$hash  $(Split-Path -Leaf $zip)" -Encoding ASCII
    $script:Summary.results.bundle = [ordered]@{ zip = $zip; sha256 = $hash; bytes = (Get-Item -LiteralPath $zip).Length }
    Remove-Item -LiteralPath $stage -Recurse -Force
    return "$zip ($([math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)) MB)"
}

function Test-BundleChecksums([string]$Stage) {
    foreach ($line in Get-Content -LiteralPath (Join-Path $Stage 'SHA256SUMS.txt')) {
        if ($line -match '^([0-9a-f]{64})\s+(.+)$') {
            $actual = (Get-FileHash -LiteralPath (Join-Path $Stage $Matches[2]) -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $Matches[1]) { throw "Checksum mismatch: $($Matches[2])" }
        }
    }
    Write-Log '    checksums OK'
}

# Collection progress (data/ops/history-progress.json) is not in the database, but the calculations read it: a 건축HUB
# year counts as finished (not 잠정값, usable as the reduction baseline) only when it says DONE. It travels with the
# bundle as collection-progress.json, reduced to status/scope fields (no free-text reasons, no times).
function Export-CollectionProgress([string]$Destination) {
    $source = Join-Path $Root 'data\ops\history-progress.json'
    if (-not (Test-Path -LiteralPath $source)) { return $false }
    $state = [System.IO.File]::ReadAllText($source) | ConvertFrom-Json
    $items = [ordered]@{}
    foreach ($p in $state.items.PSObject.Properties) {
        $item = [ordered]@{}
        foreach ($field in @('status', 'scope', 'probe_version', 'passes')) {
            if ($null -ne $p.Value.$field) { $item[$field] = $p.Value.$field }
        }
        $items[$p.Name] = $item
    }
    $json = [ordered]@{ runs = @(); items = $items } | ConvertTo-Json -Depth 5
    # No BOM: the API reads it as JSON text.
    [System.IO.File]::WriteAllText($Destination, $json, (New-Object System.Text.UTF8Encoding $false))
    return $true
}

function Import-CollectionProgress([string]$Stage) {
    $source = Join-Path $Stage 'collection-progress.json'
    if (-not (Test-Path -LiteralPath $source)) { Write-Log '    note: no collection-progress.json in this bundle (older bundle: 건축HUB years may read as 잠정값)'; return }
    $target = Join-Path $Root 'data\ops\history-progress.json'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    if (Test-Path -LiteralPath $target) {
        Copy-Item -LiteralPath $target -Destination (Join-Path $RunDir 'history-progress.before-import.json')
        Write-Log '    kept the previous history-progress.json in the run folder'
    }
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Log '    collection progress restored (data/ops/history-progress.json)'
}

function Invoke-ImportBundle {
    if (-not $BundlePath -or -not (Test-Path -LiteralPath $BundlePath)) { throw 'Use -BundlePath <carbon-dss-bundle-*.zip>' }
    $stage = Join-Path $RunDir 'bundle'
    Expand-ZipToFolder $BundlePath $stage
    Test-BundleChecksums $stage
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path -LiteralPath $envFile)) {
        # New PC: compose needs .env. Keys are never part of a bundle; fill them in afterwards.
        Copy-Item -LiteralPath (Join-Path $Root '.env.example') -Destination $envFile
        Write-Log '    created .env from .env.example (API keys are empty; add them later)'
    }
    Assert-Native (Compose-Main @('up', '-d', '--wait', 'postgres', 'redis')) 'postgres start'
    Wait-Postgres 'main'
    $existing = Get-TableCounts 'main'
    $nonEmpty = @($existing.GetEnumerator() | Where-Object { $_.Value -gt 0 })
    if ($existing.Count -gt 0) { throw "Target database already has $($existing.Count) tables ($($nonEmpty.Count) non-empty). Import only into an empty database; back it up and use a new PC/volume instead." }
    $conflicts = @()
    if (Test-Path -LiteralPath (Join-Path $stage 'raw.zip')) {
        $rawStage = Join-Path $stage 'raw'
        Expand-ZipToFolder (Join-Path $stage 'raw.zip') $rawStage
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
    $imported = Get-TableCounts 'main'
    Set-Content -LiteralPath (Join-Path $RunDir 'imported-counts.tsv') -Value @($imported.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" }) -Encoding UTF8
    $problems = Compare-Counts (Read-CountFile (Join-Path $stage 'table-counts.tsv')) $imported
    $script:Summary.results.import = [ordered]@{ bundle = $BundlePath; raw_conflicts_kept_local = $conflicts; mismatches = $problems }
    Save-Summary
    if ($problems.Count) { throw "Row count mismatch after import: $($problems -join '; ')" }
    Import-CollectionProgress $stage
    Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'api', 'worker', 'frontend')) 'service start'
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 60
    $map = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/map" -TimeoutSec 120
    $web = Invoke-WebCheck "http://127.0.0.1:$WebPort/map"
    $grids = @($map.grids.features).Count
    $script:Summary.results.import_services = [ordered]@{ health = $health.status; grids = $grids; web_status = $web.StatusCode }
    Save-Summary
    if ($health.status -ne 'ok' -or $grids -lt 1 -or $web.StatusCode -ne 200) { throw 'imported services did not pass health/map/web checks' }
    # The bundle's simulation cases must give the same values on this PC (docs/USER_MANUAL.md 9절).
    $casesText = 'no simulation cases in this bundle'
    $casesError = $null
    $bundleCases = Join-Path $stage 'simulation_cases.json'
    if (Test-Path -LiteralPath $bundleCases) {
        try { $casesText = Invoke-CaseCheck $bundleCases } catch { $casesError = $_.Exception.Message }
    }
    Remove-Item -LiteralPath $stage -Recurse -Force
    if ($casesError) { throw "imported $($imported.Count) tables with identical row counts, but $casesError" }
    return "imported $($imported.Count) tables with identical row counts; health=$($health.status); grids=$grids; web=$($web.StatusCode); raw conflicts kept local: $($conflicts.Count); $casesText"
}

function Invoke-MergeBundle {
    # Adds a teammate's bundle to this (non-empty) database. Nothing here is overwritten: rows are matched on
    # natural keys by app.merge_bundle inside the api container, raw files only fill paths that do not exist yet.
    if (-not $BundlePath -or -not (Test-Path -LiteralPath $BundlePath)) { throw 'Use -BundlePath <carbon-dss-bundle-*.zip>' }
    $stage = Join-Path $RunDir 'bundle'
    Expand-ZipToFolder $BundlePath $stage
    Test-BundleChecksums $stage
    Assert-Native (Compose-Main @('up', '-d', '--wait', 'postgres', 'redis', 'api')) 'services start'
    Wait-Postgres 'main'
    if (-not $DryRun) { Write-Log ('    backup before merge: ' + (Invoke-Backup 'before-merge')) }
    $raw = [ordered]@{ copied = 0; identical = 0; kept_local = @() }
    if (Test-Path -LiteralPath (Join-Path $stage 'raw.zip')) {
        $rawStage = Join-Path $stage 'raw'
        Expand-ZipToFolder (Join-Path $stage 'raw.zip') $rawStage
        $rawTarget = Join-Path $Root 'data\raw'
        foreach ($file in Get-ChildItem -LiteralPath $rawStage -Recurse -File) {
            $relative = $file.FullName.Substring($rawStage.Length).TrimStart('\', '/')
            $target = Join-Path $rawTarget $relative
            if (Test-Path -LiteralPath $target) {
                if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) { $raw.identical += 1 } else { $raw.kept_local += $relative.Replace('\', '/') }
                continue
            }
            if (-not $DryRun) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
                Copy-Item -LiteralPath $file.FullName -Destination $target
            }
            $raw.copied += 1
        }
    }
    Write-Log "    raw files: new $($raw.copied), identical $($raw.identical), kept local (content differs) $($raw.kept_local.Count)"
    # The bundle's database goes into a throwaway database on the same server; only the merged tables are restored.
    $source = 'dss_merge_src'
    $psql = @('exec', '-T', 'postgres', 'psql', '-U', 'carbon', '-v', 'ON_ERROR_STOP=1')
    $tables = (Compose-Main @('exec', '-T', 'api', 'python', '-m', 'app.merge_bundle', '--list-tables')).Lines | Where-Object { $_ -match '^[a-z0-9_]+$' }
    if (-not $tables) { throw 'app.merge_bundle --list-tables returned nothing (rebuild api)' }
    try {
        Assert-Native (Compose-Main ($psql + @('-d', 'carbon', '-c', "DROP DATABASE IF EXISTS $source WITH (FORCE)"))) 'drop old merge source'
        Assert-Native (Compose-Main ($psql + @('-d', 'carbon', '-c', "CREATE DATABASE $source"))) 'create merge source'
        Assert-Native (Compose-Main ($psql + @('-d', $source, '-c', 'CREATE EXTENSION IF NOT EXISTS postgis'))) 'postgis in merge source'
        Assert-Native (Compose-Main @('cp', (Join-Path $stage 'db.dump'), 'postgres:/tmp/dss-merge.dump')) 'copy dump'
        $restoreArgs = @('exec', '-T', 'postgres', 'pg_restore', '-U', 'carbon', '-d', $source, '--no-owner', '--no-privileges')
        foreach ($t in $tables) { $restoreArgs += @('-t', $t) }
        $restore = Compose-Main ($restoreArgs + @('/tmp/dss-merge.dump'))
        Write-Log "    pg_restore into $source exit $($restore.Code)"
        $mergeArgs = @('exec', '-T', 'api', 'python', '-m', 'app.merge_bundle', '--source-db', $source, '--raw-manifest', "$ContainerRunDir/bundle/raw-manifest.csv", '--out', "$ContainerRunDir/merge.json")
        if ($DryRun) { $mergeArgs += '--dry-run' }
        $merged = Compose-Main $mergeArgs
        $reportFile = Join-Path $RunDir 'merge.json'
        if (-not (Test-Path -LiteralPath $reportFile)) { Assert-Native $merged 'app.merge_bundle'; throw 'merge.json missing' }
        $report = Get-Content -LiteralPath $reportFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } finally {
        Compose-Main ($psql + @('-d', 'carbon', '-c', "DROP DATABASE IF EXISTS $source WITH (FORCE)")) | Out-Null
        Compose-Main @('exec', '-T', 'postgres', 'rm', '-f', '/tmp/dss-merge.dump') | Out-Null
    }
    $script:Summary.results.merge = [ordered]@{ bundle = $BundlePath; dry_run = [bool]$DryRun; raw = $raw; totals = $report.totals; report = $reportFile }
    Save-Summary
    $failed = @($report.tables | Where-Object { $_.status -eq 'error' })
    if ($failed.Count) { throw "merge failed for: $(($failed | ForEach-Object { "$($_.table) ($($_.message))" }) -join '; ')" }
    $added = @($report.tables | Where-Object { $_.inserted -gt 0 } | ForEach-Object { "$($_.table) +$($_.inserted)" })
    Remove-Item -LiteralPath $stage -Recurse -Force   # merge.json and summary.json stay in the run folder
    if (-not $DryRun -and $report.totals.inserted -gt 0) {
        # Map and region summaries are memoised in the api process.
        Assert-Native (Compose-Main @('restart', 'api')) 'restart api'
    }
    $mode = if ($DryRun) { 'dry run (nothing written)' } else { 'merged' }
    return "$mode; bundle rows $($report.totals.source_rows), already here $($report.totals.matched) (identical $($report.totals.identical), kept ours $($report.totals.differing)), added $($report.totals.inserted): $($added -join ', '); raw new $($raw.copied), kept local $($raw.kept_local.Count)"
}

function Invoke-VerifyBundle {
    # New-PC simulation on this machine: export -> clean git clone of HEAD -> import into a separate project.
    $exported = Invoke-ExportBundle
    $zip = $script:Summary.results.bundle.zip
    # -OutDir: the clean clone (and the raw files it imports) go to that drive and are removed afterwards.
    $clone = if ($OutDir) { Join-Path $OutDir "verify-$Stamp" } else { Join-Path $RunDir 'clean-clone' }
    $dirty = Invoke-Native -File 'git' -Arguments @('status', '--porcelain', '--untracked-files=no')
    $uncommitted = @($dirty.Lines | Where-Object { $_ -and $_ -notmatch '\.idea/' })
    if ($uncommitted.Count) { Write-Log "    note: $($uncommitted.Count) uncommitted tracked change(s) are not part of the clean clone" }
    Assert-Native (Invoke-Native -File 'git' -Arguments @('clone', '--quiet', '--no-hardlinks', $Root, $clone)) 'git clone (clean checkout of HEAD)'
    $head = (Invoke-Native -File 'git' -Arguments @('-C', $clone, 'rev-parse', '--short', 'HEAD')).Lines | Select-Object -Last 1
    $project = 'carbon-urban-dss-importtest'
    $saved = @{ DSS_PROJECT = $env:DSS_PROJECT; DSS_COMPOSE_OVERRIDE = $env:DSS_COMPOSE_OVERRIDE; DSS_API_PORT = $env:DSS_API_PORT; DSS_WEB_PORT = $env:DSS_WEB_PORT }
    $env:DSS_PROJECT = $project; $env:DSS_COMPOSE_OVERRIDE = 'compose.validation.yaml'; $env:DSS_API_PORT = '8010'; $env:DSS_WEB_PORT = '5190'
    $stepLog = Join-Path $RunDir 'import-test.log'
    try {
        $child = Invoke-Native -File 'powershell.exe' -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $clone 'scripts\dss.ps1'), '-Action', 'ImportBundle', '-BundlePath', $zip) -StepLog $stepLog
    } finally {
        foreach ($key in $saved.Keys) { Set-Item -Path "env:$key" -Value $saved[$key] -ErrorAction SilentlyContinue; if ($null -eq $saved[$key]) { Remove-Item -Path "env:$key" -ErrorAction SilentlyContinue } }
    }
    $childRun = Get-Content -LiteralPath (Join-Path $clone 'data\ops\latest.txt') -ErrorAction SilentlyContinue | Select-Object -First 1
    $childSummary = if ($childRun) { Get-Content -LiteralPath (Join-Path $clone "data\ops\$childRun\summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    # Remove only the throwaway import-test project and its volumes.
    if ($project -notmatch 'importtest$') { throw 'Refusing to remove a non-test project.' }
    Invoke-Native -File 'docker' -Arguments @('compose', '-p', $project, '-f', (Join-Path $clone 'compose.yaml'), '-f', (Join-Path $clone 'compose.validation.yaml'), 'down', '--remove-orphans') -StepLog $stepLog | Out-Null
    foreach ($volume in @("$($project)_postgres_data", "$($project)_redis_data")) { Invoke-Native -File 'docker' -Arguments @('volume', 'rm', '-f', $volume) -StepLog $stepLog | Out-Null }
    $script:Summary.results.verify_bundle = [ordered]@{ bundle = $zip; clone_head = $head; exit = $child.Code; child_steps = $childSummary.steps; child_results = $childSummary.results }
    Save-Summary
    if ($childRun) {
        foreach ($name in @('summary.json', 'cases-check.json')) {
            $file = Join-Path $clone "data\ops\$childRun\$name"
            if (Test-Path -LiteralPath $file) { Copy-Item -LiteralPath $file -Destination (Join-Path $RunDir "import-test-$name") }
        }
    }
    if ($OutDir -and $clone.StartsWith($OutDir) -and (Test-Path -LiteralPath (Join-Path $clone 'scripts\dss.ps1'))) {
        Remove-Item -LiteralPath $clone -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "    removed the clean clone $clone (results copied to $RunDir)"
    }
    if ($child.Code -ne 0) { throw "import in clean clone failed: $(($child.Lines | Where-Object { $_ -match 'FAIL' } | Select-Object -Last 2) -join ' | ')" }
    $importStep = $childSummary.steps | Where-Object { $_.name -eq 'Import team bundle' } | Select-Object -Last 1
    return "clean clone @ ${head}: $($importStep.detail) ($exported)"
}

# ----------------------------------------------------------------------------
$ok = $true
$selected = $Action
if ($Action -notin @('Doctor', 'All')) {
    if (-not (Invoke-Step 'Docker engine' { Start-DockerEngine })) { $selected = 'Skip'; $ok = $false }
}
if ($selected -in @('Status', 'Probe', 'Collect', 'CollectHistory', 'CollectAll', 'Snapshot', 'MergeBundle', 'VerifyCases')) {
    # app.ops runs inside the api image; make sure it contains the current code first.
    # --force-recreate: containers must pick up .env changes (new API keys) as well as new code.
    if (-not (Invoke-Step 'Services up to date' { Assert-Native (Compose-Main @('up', '-d', '--build', '--force-recreate', '--wait', 'api', 'worker')) 'compose up --build'; 'api/worker rebuilt with current code and .env' })) { $selected = 'Skip'; $ok = $false }
}
switch ($selected) {
    'Doctor' { $ok = Invoke-Step 'Doctor' { Invoke-Doctor } }
    'Status' { $ok = Invoke-Step 'Status' { $s = Invoke-Ops @('status') 'status.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count), raw=$($s.Json.raw.files)" } }
    'Backup' { $ok = Invoke-Step 'Backup' { Invoke-Backup 'manual' } }
    'Rebuild' { $ok = Invoke-Step 'Rebuild services' { Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'postgres', 'redis', 'api', 'worker', 'frontend')) 'compose up --build'; 'api/worker/frontend rebuilt' } }
    'Probe' {
        Invoke-Step 'Probe data.go.kr' { $p = Invoke-Ops @('probe', 'datagokr') 'probe-datagokr.json'; ($p.Json.steps | ForEach-Object { "$($_.step):$($_.result_code) items=$($_.items)" }) -join ' ' } | Out-Null
        $ok = Invoke-Step 'Probe SGIS' { $p = Invoke-Ops @('probe', 'sgis') 'probe-sgis.json'; ($p.Json.steps | ForEach-Object { "$($_.step):$($_.errCd)$($_.ok)" }) -join ' ' }
        $ok = (Invoke-Step 'Probe VWorld' { $p = Invoke-Ops @('probe', 'vworld') 'probe-vworld.json'; "working_domain=$($p.Json.working_domain); " + (($p.Json.steps | ForEach-Object { "$($_.step)[$($_.domain)]:$($_.status) $($_.error.code) features=$($_.features)" }) -join ' ') }) -and $ok
    }
    'Collect' { $ok = Invoke-Step 'Staged collection' { Invoke-Collect } }
    { $_ -in @('CollectHistory', 'CollectAll') } {
        $ok = Invoke-Step 'Backup before back-fill' { Invoke-Backup 'before-history' }
        if ($ok) { $ok = Invoke-Step 'Services up to date' { Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'api', 'worker', 'frontend')) 'compose up api worker frontend'; 'api/worker/frontend rebuilt' } }
        if ($ok) { $ok = Invoke-Step "Back-fill $FromYear-$ToYear" { Invoke-CollectHistory } }
        Invoke-Step 'Status after back-fill' { $s = Invoke-Ops @('status') 'status-after.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count)" } | Out-Null
    }
    'Snapshot' { $ok = Invoke-Step 'API snapshot' { Invoke-Snapshot } }
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
    'MergeBundle' { $ok = Invoke-Step 'Merge team bundle' { Invoke-MergeBundle } }
    'VerifyBundle' { $ok = Invoke-Step 'New-PC bundle import (clean clone)' { Invoke-VerifyBundle } }
    'VerifyCases' { $ok = Invoke-Step 'Simulation cases (verify-cases)' { Invoke-CaseCheck $CasesPath } }
    'All' {
        $ok = Invoke-Step 'Doctor' { Invoke-Doctor }
        if ($ok) {
            $ok = Invoke-Step 'Backup before changes' { Invoke-Backup 'before' }
            if ($ok) {
                $ok = Invoke-Step 'Rebuild services' { Assert-Native (Compose-Main @('up', '-d', '--build', '--wait', 'postgres', 'redis', 'frontend')) 'compose up --build'; Assert-Native (Compose-Main @('up', '-d', '--build', '--force-recreate', '--wait', 'api', 'worker')) 'recreate api/worker'; 'api/worker (recreated with current .env)/frontend rebuilt' }
            }
            if ($ok) {
                Invoke-Step 'Status before collection' { $s = Invoke-Ops @('status') 'status-before.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count), raw=$($s.Json.raw.files)" } | Out-Null
                Invoke-Step 'Probe data.go.kr' { $p = Invoke-Ops @('probe', 'datagokr') 'probe-datagokr.json'; ($p.Json.steps | ForEach-Object { "$($_.step):$($_.result_code) items=$($_.items)" }) -join ' ' } | Out-Null
                Invoke-Step 'Probe SGIS' { $p = Invoke-Ops @('probe', 'sgis') 'probe-sgis.json'; ($p.Json.steps | ForEach-Object { "$($_.step):$($_.errCd)$($_.ok)" }) -join ' ' } | Out-Null
                Invoke-Step 'Probe VWorld' { $p = Invoke-Ops @('probe', 'vworld') 'probe-vworld.json'; "working_domain=$($p.Json.working_domain); " + (($p.Json.steps | ForEach-Object { "$($_.step)[$($_.domain)]:$($_.status) $($_.error.code) features=$($_.features)" }) -join ' ') } | Out-Null
                if (-not $SkipCollect) { Invoke-Step 'Staged collection' { Invoke-Collect } | Out-Null }
                Invoke-Step 'Status after collection' { $s = Invoke-Ops @('status') 'status-after.json'; "tables=$(@($s.Json.table_counts.PSObject.Properties).Count), raw=$($s.Json.raw.files)" } | Out-Null
                Invoke-Step 'API snapshot' { Invoke-Snapshot } | Out-Null
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
                Invoke-Step 'New-PC bundle import (clean clone)' { Invoke-VerifyBundle } | Out-Null
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
