param([string] $SdkDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'target/native-player-sdk'))
$ErrorActionPreference = 'Stop'
if (-not $PSBoundParameters.ContainsKey('SdkDirectory') -and $env:LAZYBUDDY_SDK_DIR) { $SdkDirectory = $env:LAZYBUDDY_SDK_DIR }
$repo = Split-Path -Parent $PSScriptRoot
$sdk = [IO.Path]::GetFullPath($SdkDirectory)
$downloads = Join-Path $repo 'target/release-runtime-downloads'
$gst = Join-Path $sdk 'PFiles64/gstreamer/1.0/msvc_x86_64'
if ($sdk -eq [IO.Path]::GetFullPath($downloads)) { throw 'MSI source and administrative image must be separate.' }
New-Item -ItemType Directory -Force $sdk,$downloads | Out-Null
foreach ($package in @(
    @('gstreamer-1.0-msvc-x86_64-1.26.11.msi','31cbc21fa0950b5c1e79c80959b2799805cb05a7a35953a13a9f790776137605','bin/gstreamer-1.0-0.dll'),
    @('gstreamer-1.0-devel-msvc-x86_64-1.26.11.msi','af0a0720692052aaf5fb0cf2847ef34a87016ef0f914328d516f049e6c86f587','bin/pkg-config.exe')
)) {
    $marker = Join-Path $gst $package[2]
    if (Test-Path -LiteralPath $marker) { continue }
    # Administrative extraction copies the MSI into TARGETDIR; never download it there.
    $archive = Join-Path $downloads $package[0]
    if (!(Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -Uri ("https://gstreamer.freedesktop.org/pkg/windows/1.26.11/msvc/"+$package[0]) -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive).Hash -ne $package[1]) { throw 'GStreamer checksum mismatch.' }
    $log = Join-Path $downloads ($package[0]+'.log')
    $process = Start-Process msiexec.exe -ArgumentList @('/a',('"'+$archive+'"'),'/qn',('TARGETDIR="'+$sdk+'"'),'/L*v',('"'+$log+'"')) -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $marker)) { throw "SDK extraction failed: $($process.ExitCode); log: $log" }
    Remove-Item -LiteralPath $archive
}
