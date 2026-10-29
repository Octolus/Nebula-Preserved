param(
    [switch]$Start,
    [string]$Python = 'python',
    [string]$StateDirectory
)
$ErrorActionPreference = 'Stop'
$outputRoot = Split-Path -Parent $PSScriptRoot
$workspace = $outputRoot
if (-not $StateDirectory) { $StateDirectory = Join-Path $workspace 'private-state' }
$state = [IO.Path]::GetFullPath($StateDirectory)
if (-not $Start) {
    Write-Output 'No process or listener started. Explicit -Start enables the reviewed Nexus integration profile.'
    exit 2
}
$Python = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$build = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'build-validation.json') -Raw | ConvertFrom-Json
if ($build.exit_code -ne 0 -or -not $build.sources_unchanged_during_build) { throw 'A new successful source-bound Unity build is required' }
& $Python -m unittest discover -s (Join-Path $outputRoot 'backend/tests') -q
if ($LASTEXITCODE -ne 0) { throw 'Portable backend tests must pass before starting' }
foreach ($row in $build.source_hashes) {
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $row.path) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row.sha256) {
        throw "Unity build input changed: $($row.path)"
    }
}
$exe = Join-Path $PSScriptRoot 'build\NebulaMirrorProbe.exe'
$assembly = Join-Path $PSScriptRoot 'build\NebulaMirrorProbe_Data\Managed\Assembly-CSharp.dll'
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $build.executable_sha256 -or
    (Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant() -ne $build.managed_assembly_sha256) {
    throw 'Built artifact changed after validation'
}
$busy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
    Where-Object { $_.Port -eq 8080 -or $_.Port -eq 28000 })
if ($busy.Count) { throw 'Integration port 8080 or 28000 is already in use; existing processes were left alone' }
New-Item -ItemType Directory -Path $state -Force | Out-Null
$runId = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$http = $null
$instance = $null
try {
    $http = Start-Process -FilePath $Python -ArgumentList @(
        ('"' + (Join-Path $outputRoot 'backend\server.py') + '"'), '--listen', '--bind', '127.0.0.1',
        '--advertise-ip', '127.0.0.1', '--port', '8080', '--state-dir', ('"' + $state + '"'),
        '--core-test-profile', 'nexus-core-v1') -WorkingDirectory $workspace -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $state "http-$runId.stdout.log") `
        -RedirectStandardError (Join-Path $state "http-$runId.stderr.log")
    # The instance constructor reads this export immediately. On a new state
    # directory the HTTP process must finish its first publication before Unity.
    $httpReady = $false
    $startupDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $startupDeadline) {
        if ($http.HasExited) { throw 'HTTP service exited before initial state publication' }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/preservation/health' -TimeoutSec 1
            $accountsPath = Join-Path $state 'instance-accounts.json'
            if ($health.service -eq 'nebula-preservation' -and (Test-Path -LiteralPath $accountsPath)) {
                $accounts = Get-Content -LiteralPath $accountsPath -Raw | ConvertFrom-Json
                if ($accounts.format_version -eq 1) { $httpReady = $true; break }
            }
        }
        catch { }
        Start-Sleep -Milliseconds 200
    }
    if (-not $httpReady) { throw 'HTTP service did not publish a valid initial account snapshot in time' }
    $instance = Start-Process -FilePath $exe -ArgumentList @(
        '-batchmode', '-nographics', '-logFile', ('"' + (Join-Path $state "unity-$runId.log") + '"'),
        '--nebula-instance', '--nebula-state-dir', ('"' + $state + '"'),
        '--nebula-instance-id', 'integration-nexus', '--nebula-space', 'Nexus',
        '--nebula-bind', '127.0.0.1', '--nebula-advertise-ip', '127.0.0.1', '--nebula-port', '28000',
        '--nebula-core-test-profile', 'nexus-core-v1') -WorkingDirectory (Join-Path $PSScriptRoot 'build') `
        -WindowStyle Hidden -PassThru
    $run = [ordered]@{
        kind = 'explicit_nexus_core_integration_start'
        utc = [DateTime]::UtcNow.ToString('o')
        state_directory = $state
        profile = 'nexus-core-v1'
        http_pid = $http.Id
        instance_pid = $instance.Id
        client_started = $false
        startup_requested = $true
        actual_bind_verified = $false
        game_ready = $false
        networking_parity_proven = $false
    }
    $run | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $state "runtime-start-$runId.json") -Encoding utf8
    $run | ConvertTo-Json -Depth 4
}
catch {
    if ($instance -and -not $instance.HasExited) { Stop-Process -Id $instance.Id }
    if ($http -and -not $http.HasExited) { Stop-Process -Id $http.Id }
    throw
}

