param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../../build/windows-visual')
)

$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw 'Install Visual Studio Build Tools with Desktop development with C++ and the Windows SDK.'
}
$architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
$target = switch ($architecture) {
    AMD64 { 'x64' }
    ARM64 { 'arm64' }
    default { throw "Unsupported Windows architecture: $architecture" }
}
$component = if ($target -eq 'arm64') { 'Microsoft.VisualStudio.Component.VC.Tools.ARM64' } else { 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' }
$installation = & $vswhere -latest -products '*' -requires $component -property installationPath
if (-not $installation) { throw "Visual Studio C++ Build Tools for $target were not found." }
$vcvars = Join-Path $installation 'VC/Auxiliary/Build/vcvarsall.bat'
$environment = & $env:ComSpec /d /s /c ('""{0}" {1} >nul && set"' -f $vcvars, $target)
if ($LASTEXITCODE -ne 0) { throw "Could not initialize the Visual C++ $target toolchain." }
$originalEnvironment = @{}
try {
    foreach ($line in $environment) {
        if ($line -match '^([^=]+)=(.*)$') {
            $originalEnvironment[$Matches[1]] = [Environment]::GetEnvironmentVariable($Matches[1], 'Process')
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
        }
    }
    $projection = Join-Path $env:WindowsSdkDir ('Include/' + $env:WindowsSDKVersion.TrimEnd('\') + '/cppwinrt')
    if (-not (Test-Path -LiteralPath (Join-Path $projection 'winrt/Windows.Graphics.Capture.h'))) {
        throw 'Install the Windows SDK C++/WinRT headers.'
    }
    $build = New-Item -ItemType Directory -Force -Path $OutputDirectory
    $binary = Join-Path $build.FullName 'windows-visual.exe'
    Push-Location -LiteralPath $build.FullName
    try {
        $compilerArgs = @(
            '/nologo', '/std:c++17', '/EHsc', '/W4', '/O2', '/MT', '/DNOMINMAX', '/DWIN32_LEAN_AND_MEAN',
            "/I$projection", (Join-Path $PSScriptRoot 'capture.cpp'), "/Fe:$binary",
            '/link', '/INCREMENTAL:NO', '/Brepro', 'd3d11.lib', 'dxgi.lib', 'dwmapi.lib', 'windowscodecs.lib',
            'ole32.lib', 'oleaut32.lib', 'user32.lib', 'windowsapp.lib'
        )
        & cl.exe @compilerArgs
        if ($LASTEXITCODE -ne 0) { throw 'Windows visual helper build failed.' }
    } finally {
        Pop-Location
    }
    & $binary --version
    if ($LASTEXITCODE -ne 0) { throw 'The built helper could not run.' }
    Write-Output $binary
} finally {
    foreach ($name in $originalEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process')
    }
}
