"""Build the shared desktop app on the current OS; no application-code forks.

Run: python -m pip install -r requirements-build.txt
     python build_desktop.py
Native installers: python build_desktop.py --native
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from app_metadata import APP_ID, APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
RESOURCES = BUILD / "desktop-resources"
BUNDLES = BUILD / "desktop-dist"


def architecture(machine=None):
    value = (machine or platform.machine()).lower()
    if value in ("x86_64", "amd64"):
        return "x86_64"
    if value in ("arm64", "aarch64"):
        return "arm64"
    raise ValueError(f"Unsupported architecture: {value}")


def run(args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def icons():
    # Generate all native icon formats from one editable vector source.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer = QSvgRenderer(str(ROOT / "packaging" / "jumptrack.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid application icon")
    renderer.render(painter)
    painter.end()
    image.save(str(RESOURCES / "jumptrack.png"))
    with Image.open(RESOURCES / "jumptrack.png") as bitmap:
        bitmap.save(
            RESOURCES / "jumptrack.ico",
            sizes=[(n, n) for n in (16, 32, 48, 64, 128, 256)],
        )
        bitmap.save(RESOURCES / "jumptrack.icns")
        bitmap.resize((256, 256)).save(RESOURCES / "jumptrack-256.png")
    app.quit()


def version_resource():
    version = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
    (RESOURCES / "windows-version.txt").write_text(
        "VSVersionInfo(\n"
        f" ffi=FixedFileInfo(filevers={version!r}, prodvers={version!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),\n"
        " kids=[StringFileInfo([StringTable('040904B0', [\n"
        f" StringStruct('FileDescription', '{APP_NAME} Desktop'),\n"
        f" StringStruct('FileVersion', '{APP_VERSION}'),\n"
        f" StringStruct('ProductName', '{APP_NAME}'),\n"
        f" StringStruct('ProductVersion', '{APP_VERSION}'),\n"
        " StringStruct('OriginalFilename', 'JumpTrack.exe')\n"
        " ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n",
        encoding="utf-8",
    )


def zip_directory(folder, target):
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent))


def download_tool(name):
    """Fetch only the pinned, SHA-256-verified upstream AppImage tool/runtime."""
    pins = json.loads((ROOT / "packaging" / "appimage-tools.json").read_text())
    item = pins[name]
    destination = BUILD / "tools" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.exists()
        and hashlib.sha256(destination.read_bytes()).hexdigest() == item["sha256"]
    ):
        return destination
    with urllib.request.urlopen(item["url"], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError(
            f"Checksum mismatch downloading {name}; refusing to execute it"
        )
    destination.write_bytes(data)
    destination.chmod(0o755)
    return destination


def linux_appimage(bundle, stem, arch):
    appdir = BUILD / "JumpTrack.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    shutil.copytree(bundle, appdir / "usr" / "lib" / "jumptrack")
    (appdir / "AppRun").write_text(
        '#!/bin/sh\nappdir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$appdir/usr/lib/jumptrack/JumpTrack" "$@"\n',
        encoding="utf-8",
    )
    (appdir / "AppRun").chmod(0o755)
    (appdir / "jumptrack.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=JumpTrack\n"
        "Comment=Bluetooth altimeter settings and jump profiles\n"
        "Exec=JumpTrack\nIcon=jumptrack\nCategories=Utility;\nTerminal=false\n",
        encoding="utf-8",
    )
    shutil.copy2(RESOURCES / "jumptrack-256.png", appdir / "jumptrack.png")
    shutil.copy2(appdir / "jumptrack.png", appdir / ".DirIcon")
    tool_arch = "aarch64" if arch == "arm64" else arch
    tool = download_tool(f"appimagetool-{tool_arch}.AppImage")
    runtime = download_tool(f"runtime-{tool_arch}")
    target = DIST / f"{stem}.AppImage"
    environment = {
        **os.environ,
        "ARCH": tool_arch,
        "APPIMAGE_EXTRACT_AND_RUN": "1",
        "NO_APPSTREAM": "1",
    }
    run([tool, "--runtime-file", runtime, appdir, target], env=environment)
    target.chmod(0o755)
    return target


def windows_installer(bundle, stem):
    compiler = shutil.which("iscc") or shutil.which("ISCC")
    if compiler is None:
        candidate = (
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Inno Setup 6"
            / "ISCC.exe"
        )
        if candidate.is_file():
            compiler = str(candidate)
    if compiler is None:
        raise RuntimeError(
            "Install Inno Setup 6 to build --native, or omit --native for a portable ZIP"
        )
    run(
        [
            compiler,
            f"/DAppVersion={APP_VERSION}",
            f"/DBundlePath={bundle}",
            f"/DOutputPath={DIST}",
            f"/DInstallerName={stem}-Setup",
            f"/DIconPath={RESOURCES / 'jumptrack.ico'}",
            ROOT / "packaging" / "windows.iss",
        ]
    )
    return DIST / f"{stem}-Setup.exe"


def macos_dmg(bundle, stem):
    stage = BUILD / "dmg"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    run(["ditto", bundle, stage / "JumpTrack.app"])
    (stage / "Applications").symlink_to("/Applications")
    shutil.copy2(ROOT / "docs" / "INSTALLING.md", stage / "START-HERE.txt")
    target = DIST / f"{stem}.dmg"
    run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            stage,
            "-ov",
            "-format",
            "UDZO",
            target,
        ]
    )
    return target


def smoke(executable, report, *, env=None):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "BLEAK_BACKEND")
    }
    environment.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "JUMPTRACK_LOG_DIR": str(BUILD / "smoke-logs"),
            **(env or {}),
        }
    )
    # Run away from the checkout so accidental source imports cannot hide
    # missing modules or resources in the installed bundle.
    with tempfile.TemporaryDirectory(prefix="jumptrack-smoke-") as folder:
        run(
            [executable, "--smoke-test", report],
            cwd=folder,
            env=environment,
            timeout=90,
        )
    if not json.loads(report.read_text())["ok"]:
        raise RuntimeError(f"Packaged smoke test failed; see {report}")


def smoke_native(target, report, system):
    if system == "linux":
        smoke(target, report, env={"APPIMAGE_EXTRACT_AND_RUN": "1"})
    elif system == "windows":
        with tempfile.TemporaryDirectory(prefix="jumptrack-install-") as folder:
            installed = Path(folder) / "JumpTrack"
            run(
                [
                    target,
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/SP-",
                    f"/DIR={installed}",
                ],
                timeout=180,
            )
            try:
                # Exercise an upgrade as well as a first installation. Old
                # PyInstaller libraries must not survive and shadow new ones.
                stale = installed / "_internal" / "obsolete-upgrade-test.txt"
                stale.write_text("old runtime")
                run(
                    [
                        target,
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                        "/SP-",
                        f"/DIR={installed}",
                    ],
                    timeout=180,
                )
                if stale.exists():
                    raise RuntimeError(
                        "Installer upgrade retained obsolete runtime files"
                    )
                smoke(installed / "JumpTrack.exe", report)
            finally:
                run(
                    [
                        installed / "unins000.exe",
                        "/VERYSILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                    ],
                    timeout=180,
                )
    else:
        with tempfile.TemporaryDirectory(prefix="jumptrack-dmg-") as folder:
            mount = Path(folder) / "volume"
            run(
                [
                    "hdiutil",
                    "attach",
                    "-readonly",
                    "-nobrowse",
                    "-mountpoint",
                    mount,
                    target,
                ]
            )
            try:
                smoke(
                    mount / "JumpTrack.app" / "Contents" / "MacOS" / "JumpTrack", report
                )
            finally:
                run(["hdiutil", "detach", mount])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native",
        action="store_true",
        help="Also build installer/DMG/AppImage for this OS",
    )
    parser.add_argument(
        "--check-tag",
        help="Check a release tag against the shared application version, then exit",
    )
    args = parser.parse_args(argv)
    if args.check_tag is not None:
        if args.check_tag != f"v{APP_VERSION}":
            parser.error(f"Tag must match app_metadata.py: v{APP_VERSION}")
        return 0
    arch = architecture()
    system = {"win32": "windows", "darwin": "macos", "linux": "linux"}.get(sys.platform)
    if system is None or (system == "windows" and arch != "x86_64"):
        parser.error("Supported: Windows x64; macOS/Linux x64 and ARM64")
    RESOURCES.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)
    icons()
    version_resource()
    environment = {**os.environ, "QT_API": "pyside6"}
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            BUNDLES,
            "--workpath",
            BUILD / "pyinstaller",
            ROOT / "packaging" / "JumpTrack.spec",
        ],
        cwd=ROOT,
        env=environment,
    )
    bundle = BUNDLES / ("JumpTrack.app" if system == "macos" else "JumpTrack")
    # Keep documentation beside portable executables, outside private captures.
    if system != "macos":
        shutil.copy2(ROOT / "docs" / "INSTALLING.md", bundle / "START-HERE.txt")
    stem = f"JumpTrack-{APP_VERSION}-{system}-{arch}"
    executable = bundle / (
        "Contents/MacOS/JumpTrack"
        if system == "macos"
        else "JumpTrack.exe"
        if system == "windows"
        else "JumpTrack"
    )
    smoke(executable, DIST / f"{stem}-smoke.json")
    artifacts = []
    if system == "macos":
        target = DIST / f"{stem}.zip"
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", bundle, target])
        artifacts.append(target)
    elif system == "windows":
        target = DIST / f"{stem}.zip"
        zip_directory(bundle, target)
        artifacts.append(target)
    else:
        target = DIST / f"{stem}.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            archive.add(bundle, arcname="JumpTrack")
        artifacts.append(target)
    if args.native:
        if system == "windows":
            artifacts.append(windows_installer(bundle, stem))
        elif system == "macos":
            artifacts.append(macos_dmg(bundle, stem))
        else:
            artifacts.append(linux_appimage(bundle, stem, arch))
        smoke_native(artifacts[-1], DIST / f"{stem}-native-smoke.json", system)
    manifest = {
        "app_id": APP_ID,
        "version": APP_VERSION,
        "platform": system,
        "architecture": arch,
        "python": platform.python_version(),
        "build_host": platform.platform(),
        "packages": {
            dist.metadata["Name"]: dist.version
            for dist in importlib.metadata.distributions()
        },
        "artifacts": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifacts
        },
    }
    (DIST / f"{stem}-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (DIST / f"{stem}-SHA256SUMS.txt").write_text(
        "".join(
            f"{checksum}  {name}\n" for name, checksum in manifest["artifacts"].items()
        ),
        encoding="utf-8",
    )
    print("Built:\n" + "\n".join(str(path) for path in artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
