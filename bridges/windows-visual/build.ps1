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
$installation = & $vswhere -latest -products '*' -requires $component -format json | ConvertFrom-Json
if (-not $installation) { throw "Visual Studio C++ Build Tools for $target were not found." }
$vcvars = Join-Path $installation.installationPath 'VC/Auxiliary/Build/vcvarsall.bat'
# Visual Studio 18 requires the standard coroutine header for C++/WinRT.
# Keep C++17 on Visual Studio 17 so it can reproduce the original release helper.
$cppStandard = if ([version]$installation.installationVersion -ge [version]'18.0') { '/std:c++20' } else { '/std:c++17' }
# cmd.exe needs literal quotes here, independent of the PowerShell native argument mode.
$vcvarsProcess = [System.Diagnostics.ProcessStartInfo]::new()
$vcvarsProcess.FileName = $env:ComSpec
$vcvarsProcess.Arguments = '/d /s /c ""{0}" {1} >nul && set"' -f $vcvars, $target
$vcvarsProcess.UseShellExecute = $false
$vcvarsProcess.RedirectStandardOutput = $true
$process = [System.Diagnostics.Process]::Start($vcvarsProcess)
try {
    $environment = $process.StandardOutput.ReadToEnd() -split '\r?\n'
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Could not initialize the Visual C++ $target toolchain." }
} finally {
    $process.Dispose()
}
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
            '/nologo', $cppStandard, '/EHsc', '/W4', '/O2', '/MT', '/DNOMINMAX', '/DWIN32_LEAN_AND_MEAN',
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
