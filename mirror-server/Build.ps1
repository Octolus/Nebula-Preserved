param(
    [string]$Unity = $env:UNITY_EDITOR
)
$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'UnityProject'
$log = Join-Path $PSScriptRoot 'build.log'
if (-not $Unity -or -not (Test-Path -LiteralPath $Unity)) { throw "Unity editor missing: $Unity" }
$sourceRoot = Join-Path $project 'Assets\Preservation'
function Get-PreservationSourceHashes {
    $files = @(Get-ChildItem -LiteralPath $sourceRoot -Filter '*.cs' -Recurse -File)
    $files += Get-Item -LiteralPath (Join-Path $project 'Assets\Editor\PreservationBuild.cs')
    $files += Get-Item -LiteralPath (Join-Path $project 'Assets\Mirror\Runtime\Transports\Telepathy\Telepathy\Server.cs')
    $files += Get-Item -LiteralPath (Join-Path $project 'Assets\Mirror\Runtime\Transports\Telepathy\TelepathyTransport.cs')
    @($files | Sort-Object FullName | ForEach-Object {
        [PSCustomObject]@{
            path = [IO.Path]::GetRelativePath($PSScriptRoot, $_.FullName).Replace('\','/')
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
}
$beforeHashes = Get-PreservationSourceHashes
$process = Start-Process -FilePath $Unity -ArgumentList @('-batchmode','-nographics','-quit','-projectPath',('"' + $project + '"'),'-executeMethod','PreservationBuild.Build','-logFile',('"' + $log + '"')) -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Unity build failed with exit code $($process.ExitCode). See $log" }
$afterHashes = Get-PreservationSourceHashes
if (($beforeHashes | ConvertTo-Json -Depth 4 -Compress) -ne ($afterHashes | ConvertTo-Json -Depth 4 -Compress)) {
    throw 'Sources changed during the build; build evidence must be regenerated after edits settle'
}
if (-not (Select-String -LiteralPath $log -SimpleMatch 'NEBULA_PROBE_BUILD_SUCCESS' -Quiet)) {
    throw 'Unity exited without the expected build-success marker'
}
$exe = Join-Path $PSScriptRoot 'build\NebulaMirrorProbe.exe'
$assembly = Join-Path $PSScriptRoot 'build\NebulaMirrorProbe_Data\Managed\Assembly-CSharp.dll'
$validation = [ordered]@{
    kind = 'compile_only_unity_build'
    utc = [DateTime]::UtcNow.ToString('o')
    unity_editor = '6000.6.3f1'
    exit_code = $process.ExitCode
    success_marker = 'NEBULA_PROBE_BUILD_SUCCESS'
    game_launched = $false
    reconstructed_listener_started = $false
    sources_unchanged_during_build = $true
    source_hashes = $afterHashes
    executable_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    managed_assembly_sha256 = (Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant()
    networking_parity_proven = $false
}
$validation | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'build-validation.json') -Encoding utf8
Write-Output (Join-Path $PSScriptRoot 'build\NebulaMirrorProbe.exe')

