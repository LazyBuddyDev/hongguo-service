$ErrorActionPreference = 'Stop'
$resolverRepo = Split-Path -Parent $PSScriptRoot
$resolverSdk = if ($env:LAZYBUDDY_SDK_DIR) { $env:LAZYBUDDY_SDK_DIR } else { Join-Path $resolverRepo 'target\native-player-sdk' }
$resolverGoPath = Join-Path $resolverSdk 'go\bin\go.exe'
if (-not (Test-Path -LiteralPath $resolverGoPath)) {
    New-Item -ItemType Directory -Path $resolverSdk -Force | Out-Null
    $resolverArchive = Join-Path $resolverSdk 'go1.27.4.windows-amd64.zip'
    Write-Host 'Preparing the private App resolver build toolchain...'
    Invoke-WebRequest -Uri 'https://go.dev/dl/go1.27.4.windows-amd64.zip' -OutFile $resolverArchive
    if ((Get-FileHash -LiteralPath $resolverArchive -Algorithm SHA256).Hash -ne '178AB98950AC69AB25069307DC6ADE79F3816E414CCE95B4DA166A115CDE1E7E') {
        throw 'Go toolchain integrity check failed.'
    }
    Expand-Archive -LiteralPath $resolverArchive -DestinationPath $resolverSdk -Force
    Remove-Item -LiteralPath $resolverArchive
}
$resolverOldCache = $env:GOCACHE
try {
    $env:GOCACHE = Join-Path $resolverRepo 'target\go-cache'
    $resolverOutput = Join-Path $resolverRepo 'target\hongguo-app-resolver.exe'
    Push-Location -LiteralPath (Join-Path $resolverRepo 'resolver')
    try {
        & $resolverGoPath build -mod=readonly -trimpath -ldflags='-s -w' -o $resolverOutput .
        if ($LASTEXITCODE -ne 0) { throw 'App resolver build failed.' }
    } finally { Pop-Location }
} finally { $env:GOCACHE = $resolverOldCache }
