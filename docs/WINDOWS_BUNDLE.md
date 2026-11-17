# Windows x64 bundle

The versioned ZIP includes the VisumWay wheel, the Windows Graphics Capture
helper, a manifest with both SHA-256 hashes, and a PowerShell installer.
You need Python 3.9 or newer. Installation uses the wheel in the ZIP and
works offline.

## Verify the release ZIP

Download the [Windows x64 ZIP](https://github.com/jay-showforge/VisumWay/releases/download/v0.2.6/VisumWay-v0.2.6-windows-x64.zip)
and [SHA256SUMS.txt](https://github.com/jay-showforge/VisumWay/releases/download/v0.2.6/SHA256SUMS.txt).
The release ZIP was built locally and tested in a fresh environment.
Compare the published hash to:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\VisumWay-v0.2.6-windows-x64.zip
```

## Verify a workflow artifact

For a bundle produced by the public GitHub build workflow, verify its
attestation before extracting the ZIP. Substitute the repository you
trust and the downloaded filename.

```powershell
gh attestation verify .\VisumWay-v0.2.6-windows-x64.zip --repo OWNER/REPO --signer-workflow OWNER/REPO/.github/workflows/windows-bundle.yml
```

See [GitHub's verification instructions](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).
For a private review copy, compare the outer ZIP hash with the SHA-256
you received through a trusted channel. The manifest inside the ZIP
checks component integrity. The helper is unsigned.

## Install

Extract the verified ZIP. From its directory:

```powershell
.\Install-VisumWay.ps1
visumway setup
visumway verify
```

Use `-Python C:\path\to\python.exe` to install into a specific Python
environment. If `visumway` is outside your PATH, use
`python -m visumway` with the same interpreter. The installing agent can
add `--agent NAME` to setup to reserve optional notifications for itself,
such as `--agent codex` or `--agent claude`. Run `visumway wakes preview`
before enabling alerts with `visumway wakes enable --agent NAME`.

The installer verifies both component hashes before installing. The
VisumWay CLI also verifies the staged helper before executing its version
check. The bundle targets x64. For other architectures, see
[Windows visual setup](WINDOWS_VISUAL.md).

## Build a candidate

On a Windows x64 checkout with the C++ build tools listed in
[Windows visual setup](WINDOWS_VISUAL.md), run:

```powershell
python -m pip install "setuptools>=70.2" wheel
python release/windows/build.py
```

The ZIP is written to `dist`. The builder can use an already reviewed
helper with `--reviewed-helper PATH --sha256 EXPECTED_DIGEST`. A local
build does not have a GitHub attestation. The manual **Build Windows
bundle** GitHub Actions workflow compiles the helper, installs the bundle
in a fresh environment, and uploads a review artifact. For public
repositories, the workflow also attests the ZIP.
