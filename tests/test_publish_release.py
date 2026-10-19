"""Publishing requires complete, verified packages and never overwrites a release."""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_metadata import APP_ID, APP_VERSION
from publish_release import TARGETS, prepare_release, publish


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        self.output = self.root / "release"
        for target in TARGETS:
            system, arch = target.split("-")
            directory = self.artifacts / target
            directory.mkdir(parents=True)
            stem = f"JumpTrack-{APP_VERSION}-{target}"
            extensions = {
                "windows": (".zip", "-Setup.exe"),
                "macos": (".zip", ".dmg"),
                "linux": (".tar.gz", ".AppImage"),
            }[system]
            hashes = {}
            for extension in extensions:
                data = f"synthetic package {target}{extension}".encode()
                filename = stem + extension
                (directory / filename).write_bytes(data)
                hashes[filename] = hashlib.sha256(data).hexdigest()
            manifest = {
                "app_id": APP_ID,
                "version": APP_VERSION,
                "platform": system,
                "architecture": arch,
                "artifacts": hashes,
            }
            (directory / f"{stem}-manifest.json").write_text(json.dumps(manifest))
            for suffix in ("smoke", "native-smoke"):
                (directory / f"{stem}-{suffix}.json").write_text(
                    json.dumps({"ok": True, "version": APP_VERSION})
                )

    def prepare(self):
        return prepare_release(
            self.artifacts, self.output, f"v{APP_VERSION}", "example/repo"
        )

    def test_complete_packages_have_public_links_and_combined_hashes(self):
        assets, notes = self.prepare()
        self.assertEqual(len(assets), 12)
        self.assertEqual(
            len((self.output / "SHA256SUMS.txt").read_text().splitlines()), 10
        )
        self.assertIn("/releases/download/", notes.read_text())
        self.assertIn("Unsigned development builds", notes.read_text())

    def test_missing_architecture_or_failed_smoke_blocks_publication(self):
        path = next(self.artifacts.rglob("*native-smoke.json"))
        path.write_text(json.dumps({"ok": False, "version": APP_VERSION}))
        with self.assertRaisesRegex(ValueError, "Smoke test"):
            self.prepare()
        path.write_text(json.dumps({"ok": True, "version": APP_VERSION}))
        next(self.artifacts.rglob("*-manifest.json")).unlink()
        with self.assertRaisesRegex(ValueError, "Missing build targets"):
            self.prepare()

    def test_corrupted_package_or_wrong_tag_blocks_publication(self):
        next(self.artifacts.rglob("*.dmg")).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.prepare()
        with self.assertRaisesRegex(ValueError, "tag must match"):
            prepare_release(self.artifacts, self.output, "v999.0.0", "example/repo")

    def test_existing_public_release_is_never_changed(self):
        assets, notes = self.prepare()
        existing = subprocess.CompletedProcess(
            [], 0, json.dumps({"isDraft": False, "assets": []})
        )
        with (
            patch("publish_release.subprocess.run", return_value=existing) as run,
            self.assertRaisesRegex(ValueError, "already public"),
        ):
            publish(assets, notes, f"v{APP_VERSION}", "example/repo")
        self.assertEqual(run.call_count, 1)

    def test_publish_happens_only_after_uploaded_hashes_are_verified(self):
        assets, notes = self.prepare()
        remote = {
            "draft": True,
            "assets": [
                {
                    "name": asset.name,
                    "size": asset.stat().st_size,
                    "digest": "sha256:"
                    + hashlib.sha256(asset.read_bytes()).hexdigest(),
                }
                for asset in assets
            ],
        }
        replies = [
            subprocess.CompletedProcess([], 1),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, json.dumps(remote)),
            subprocess.CompletedProcess([], 0),
        ]
        with patch("publish_release.subprocess.run", side_effect=replies) as run:
            publish(assets, notes, f"v{APP_VERSION}", "example/repo")
        calls = [call.args[0] for call in run.call_args_list]
        self.assertIn("--draft", calls[1])
        self.assertIn("--draft=false", calls[-1])
        self.assertEqual(calls[3][:2], ["gh", "api"])
        remote["assets"][0]["digest"] = "sha256:invalid"
        with patch("publish_release.subprocess.run", side_effect=replies) as run:
            # Replace the API response; publishing must stop before the final edit.
            replies[3] = subprocess.CompletedProcess([], 0, json.dumps(remote))
            with self.assertRaisesRegex(ValueError, "hash verification"):
                publish(assets, notes, f"v{APP_VERSION}", "example/repo")
        self.assertEqual(run.call_count, 4)
