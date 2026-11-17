param(
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($architecture -ne 'AMD64') { throw 'This VisumWay bundle requires Windows x64.' }

$manifest = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') | ConvertFrom-Json
if ($manifest.architecture -ne 'x64' -or $manifest.wheel -notmatch '^visumway-[0-9.]+-py3-none-any\.whl$') {
    throw 'Invalid VisumWay bundle manifest.'
}
$wheel = Join-Path $PSScriptRoot $manifest.wheel
$helper = Join-Path $PSScriptRoot 'windows-visual.exe'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $wheel).Hash -ne $manifest.wheel_sha256) {
    throw 'VisumWay wheel SHA-256 mismatch.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $helper).Hash -ne $manifest.helper_sha256) {
    throw 'Windows visual helper SHA-256 mismatch.'
}

& $Python -m pip install --no-index --no-deps $wheel
if ($LASTEXITCODE -ne 0) { throw 'VisumWay wheel installation failed.' }
& $Python -m visumway bridge install windows-visual $helper --sha256 $manifest.helper_sha256
if ($LASTEXITCODE -ne 0) { throw 'Windows visual helper installation failed.' }
Write-Output 'VisumWay is installed. Run visumway setup for the shared tools. Add --agent NAME to reserve notifications for the installer.'
