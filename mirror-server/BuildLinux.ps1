param(
    [string]$Unity = $env:UNITY_EDITOR
)
$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'UnityProject'
$log = Join-Path $PSScriptRoot 'build-linux.log'
if (-not $Unity -or -not (Test-Path -LiteralPath $Unity)) { throw "Unity editor missing: $Unity" }
function Get-LinuxSourceHashes {
    $files = @(Get-ChildItem -LiteralPath (Join-Path $project 'Assets\Preservation') -Filter '*.cs' -Recurse -File)
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
$beforeHashes = Get-LinuxSourceHashes
$process = Start-Process -FilePath $Unity -ArgumentList @('-batchmode','-nographics','-quit','-projectPath',('"' + $project + '"'),'-buildTarget','Linux64','-standaloneBuildSubtarget','Server','-executeMethod','PreservationBuild.BuildLinuxServer','-logFile',('"' + $log + '"')) -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Unity Linux build failed with exit code $($process.ExitCode). See $log" }
$afterHashes = Get-LinuxSourceHashes
if (($beforeHashes | ConvertTo-Json -Depth 4 -Compress) -ne ($afterHashes | ConvertTo-Json -Depth 4 -Compress)) {
    throw 'Sources changed during build; regenerate after edits settle'
}
if (-not (Select-String -LiteralPath $log -SimpleMatch 'NEBULA_LINUX_SERVER_BUILD_SUCCESS' -Quiet)) {
    throw 'Unity exited without the Linux build-success marker'
}
$output = Join-Path $PSScriptRoot 'build-linux'
$exe = Join-Path $output 'NebulaServer.x86_64'
$assembly = Join-Path $output 'NebulaServer_Data\Managed\Assembly-CSharp.dll'
$header = [IO.File]::ReadAllBytes($exe)
if ($header.Length -lt 20 -or $header[0] -ne 0x7f -or $header[1] -ne 0x45 -or $header[2] -ne 0x4c -or $header[3] -ne 0x46 -or $header[4] -ne 2 -or $header[5] -ne 1 -or [BitConverter]::ToUInt16($header,18) -ne 62) {
    throw 'Linux build is not an ELF64 little-endian x86-64 executable'
}
$artifacts = @(Get-ChildItem -LiteralPath $output -Recurse -File | Sort-Object FullName | ForEach-Object {
    [PSCustomObject]@{
        path = [IO.Path]::GetRelativePath($output,$_.FullName).Replace('\','/')
        size = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
$validation = [ordered]@{
    kind = 'compile_only_linux_dedicated_server_build'
    utc = [DateTime]::UtcNow.ToString('o')
    unity_editor = '6000.6.3f1'
    exit_code = $process.ExitCode
    success_marker = 'NEBULA_LINUX_SERVER_BUILD_SUCCESS'
    target = 'StandaloneLinux64'
    subtarget = 'Server'
    scripting_backend = 'Mono2x'
    elf64_x86_64 = $true
    game_launched = $false
    reconstructed_listener_started = $false
    linux_runtime_tested = $false
    sources_unchanged_during_build = $true
    source_hashes = $afterHashes
    artifacts = $artifacts
    executable_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    managed_assembly_sha256 = (Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant()
    networking_parity_proven = $false
}
$validation | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'build-linux-validation.json') -Encoding utf8
Write-Output $exe

