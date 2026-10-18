# One shared dependency analysis for every OS. Native launchers are the only
# platform-specific part; the GUI and BLE/session sources are never copied/forked.
import os
import runpy
import sys
from pathlib import Path

root = Path(SPECPATH).parent
metadata = runpy.run_path(str(root / "app_metadata.py"))
resources = root / "build" / "desktop-resources"
icon = resources / ("jumptrack.icns" if sys.platform == "darwin" else "jumptrack.ico")
signing = os.environ.get("JUMPTRACK_CODESIGN_IDENTITY") or None

a = Analysis(
    [str(root / "desktop_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "packaging" / "jumptrack.svg"), "assets"),
        (str(root / "docs" / "INSTALLING.md"), "docs"),
        (str(root / "docs" / "PACKAGING.md"), "docs"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["QtAgg"]}},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="JumpTrack",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon) if sys.platform in ("win32", "darwin") else None,
    version=str(resources / "windows-version.txt") if sys.platform == "win32" else None,
    codesign_identity=signing,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JumpTrack")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="JumpTrack.app",
        icon=str(icon),
        bundle_identifier=metadata["APP_ID"],
        version=metadata["APP_VERSION"],
        info_plist={
            "CFBundleShortVersionString": metadata["APP_VERSION"],
            "CFBundleVersion": metadata["APP_VERSION"],
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "NSBluetoothAlwaysUsageDescription": "JumpTrack connects to your altimeter to read jumps and configure settings you explicitly apply.",
        },
    )
