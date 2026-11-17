"""Build an offline Windows x64 release ZIP from a wheel and a native helper."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HELPER = "windows-visual.exe"


def build(output: Path, reviewed_helper: Path | None, expected: str | None) -> Path:
    with tempfile.TemporaryDirectory(prefix="visumway-release-") as tmp:
        stage = Path(tmp)
        if reviewed_helper is None:
            subprocess.run(["powershell.exe", "-NoProfile", "-File",
                            str(ROOT / "bridges" / "windows-visual" / "build.ps1"),
                            "-OutputDirectory", str(stage)], check=True)
            reviewed_helper = stage / HELPER
        native = reviewed_helper.read_bytes()
        digest = hashlib.sha256(native).hexdigest()
        if expected is not None and digest != expected.lower():
            raise ValueError("reviewed helper SHA-256 mismatch")
        if len(native) < 64 or native[:2] != b"MZ":
            raise ValueError("expected a Windows executable")
        pe_offset, = struct.unpack_from("<I", native, 60)
        if native[pe_offset:pe_offset + 6] != b"PE\0\0\x64\x86":
            raise ValueError("expected a Windows x64 helper")
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
                        "--no-build-isolation", "--wheel-dir", str(stage), str(ROOT)], check=True)
        wheel, = stage.glob("visumway-*.whl")
        version = wheel.name.split("-")[1]
        manifest = {
            "version": version,
            "architecture": "x64",
            "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "helper_sha256": digest,
        }
        output.mkdir(parents=True, exist_ok=True)
        bundle = output / f"VisumWay-v{version}-windows-x64.zip"
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zipfile:
            zipfile.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            zipfile.writestr(HELPER, native)
            zipfile.write(wheel, wheel.name)
            zipfile.write(HERE / "Install-VisumWay.ps1", "Install-VisumWay.ps1")
            zipfile.write(ROOT / "LICENSE", "LICENSE")
        return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--reviewed-helper", type=Path, help="reuse a previously built x64 helper")
    parser.add_argument("--sha256", help="trusted SHA-256 of the reviewed helper")
    args = parser.parse_args()
    if (args.reviewed_helper is None) != (args.sha256 is None):
        parser.error("--reviewed-helper and --sha256 must be provided together")
    print(build(args.output, args.reviewed_helper, args.sha256))


if __name__ == "__main__":
    main()
