"""Packaging contracts that protect versioning, resource paths and tool integrity."""

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_desktop
from app_metadata import APP_VERSION
from desktop_entry import LogStream


class PackagingTests(unittest.TestCase):
    def test_native_architecture_names_and_unknown_targets(self):
        for raw, expected in [
            ("AMD64", "x86_64"),
            ("x86_64", "x86_64"),
            ("aarch64", "arm64"),
            ("arm64", "arm64"),
        ]:
            self.assertEqual(build_desktop.architecture(raw), expected)
        with self.assertRaises(ValueError):
            build_desktop.architecture("i386")

    def test_release_tag_must_match_shared_version(self):
        self.assertEqual(build_desktop.main(["--check-tag", f"v{APP_VERSION}"]), 0)
        with (
            patch("sys.stderr", new_callable=io.StringIO),
            self.assertRaises(SystemExit) as raised,
        ):
            build_desktop.main(["--check-tag", "v999.0.0"])
        self.assertEqual(raised.exception.code, 2)

    def test_archive_preserves_bundle_layout_without_neighboring_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "JumpTrack"
            (bundle / "_internal").mkdir(parents=True)
            (bundle / "JumpTrack.exe").write_bytes(b"executable")
            (bundle / "_internal" / "resource.txt").write_text("resource")
            (root / ".jumptrack-address").write_text("PRIVATE")
            target = root / "portable.zip"
            build_desktop.zip_directory(bundle, target)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["JumpTrack/JumpTrack.exe", "JumpTrack/_internal/resource.txt"],
                )

    def test_downloads_are_verified_before_execution_and_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "packaging").mkdir()
            data = b"trusted tool"
            pins = {
                "tool": {
                    "url": "https://example.invalid/tool",
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            }
            (root / "packaging" / "appimage-tools.json").write_text(json.dumps(pins))
            with (
                patch.object(build_desktop, "ROOT", root),
                patch.object(build_desktop, "BUILD", root / "build"),
            ):
                with (
                    patch(
                        "build_desktop.urllib.request.urlopen",
                        return_value=io.BytesIO(b"corrupted"),
                    ),
                    self.assertRaisesRegex(ValueError, "Checksum mismatch"),
                ):
                    build_desktop.download_tool("tool")
                self.assertFalse((root / "build" / "tools" / "tool").exists())
                with patch(
                    "build_desktop.urllib.request.urlopen",
                    return_value=io.BytesIO(data),
                ):
                    path = build_desktop.download_tool("tool")
                with patch("build_desktop.urllib.request.urlopen") as request:
                    self.assertEqual(build_desktop.download_tool("tool"), path)
                    request.assert_not_called()

    def test_windowed_console_output_goes_to_log(self):
        stream = LogStream()
        with self.assertLogs("desktop_entry", level="INFO") as logs:
            self.assertEqual(stream.write("transport message\n"), 18)
            stream.write("\n")
        self.assertEqual(len(logs.output), 1)
        self.assertIn("transport message", logs.output[0])
