$ErrorActionPreference = 'Stop'
$resolverRepo = Split-Path -Parent $PSScriptRoot
$resolverGo = if ($env:LAZYBUDDY_GO_DIR) { $env:LAZYBUDDY_GO_DIR } else { Join-Path $resolverRepo 'target\toolchains\go' }
$resolverGoPath = Join-Path $resolverGo 'bin\go.exe'
if (-not (Test-Path -LiteralPath $resolverGoPath)) {
    $resolverDownloads = Join-Path $resolverRepo 'target\downloads'
    New-Item -ItemType Directory -Path $resolverDownloads,(Split-Path -Parent $resolverGo) -Force | Out-Null
    $resolverArchive = Join-Path $resolverDownloads 'go1.27.4.windows-amd64.zip'
    Write-Host 'Preparing the private App resolver build toolchain...'
    if (!(Test-Path -LiteralPath $resolverArchive)) { Invoke-WebRequest -Uri 'https://go.dev/dl/go1.27.4.windows-amd64.zip' -OutFile $resolverArchive }
    if ((Get-FileHash -LiteralPath $resolverArchive -Algorithm SHA256).Hash -ne '178AB98950AC69AB25069307DC6ADE79F3816E414CCE95B4DA166A115CDE1E7E') {
        throw 'Go toolchain integrity check failed.'
    }
    if ((Split-Path -Leaf $resolverGo) -ne 'go') { throw 'Go toolchain directory must end in go.' }
    Expand-Archive -LiteralPath $resolverArchive -DestinationPath (Split-Path -Parent $resolverGo) -Force
    Remove-Item -LiteralPath $resolverArchive
}
$resolverOldCache = $env:GOCACHE
try {
    $env:GOCACHE = Join-Path $resolverRepo 'target\cache\go'
    $resolverOutput = Join-Path $resolverRepo 'target\hongguo-app-resolver.exe'
    Push-Location -LiteralPath (Join-Path $resolverRepo 'resolver')
    try {
        & $resolverGoPath build -mod=readonly -trimpath -ldflags='-s -w' -o $resolverOutput .
        if ($LASTEXITCODE -ne 0) { throw 'App resolver build failed.' }
    } finally { Pop-Location }
} finally { $env:GOCACHE = $resolverOldCache }
