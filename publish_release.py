"""Verify all native CI packages and publish a public GitHub pre-release."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from app_metadata import APP_ID, APP_VERSION

TARGETS = {
    "windows-x86_64",
    "macos-arm64",
    "macos-x86_64",
    "linux-x86_64",
    "linux-arm64",
}


def prepare_release(artifacts, output, tag, repository):
    if tag != f"v{APP_VERSION}":
        raise ValueError("Release tag must match app_metadata.py")
    manifests = sorted(Path(artifacts).rglob("*-manifest.json"))
    targets, assets, hashes, builds = set(), [], {}, []
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        target = f"{manifest['platform']}-{manifest['architecture']}"
        if target not in TARGETS or target in targets:
            raise ValueError(f"Unexpected or duplicate build target: {target}")
        if manifest["version"] != APP_VERSION or manifest["app_id"] != APP_ID:
            raise ValueError(f"Build identity/version mismatch: {target}")
        targets.add(target)
        stem = f"JumpTrack-{APP_VERSION}-{target}"
        extensions = {
            "windows": (".zip", "-Setup.exe"),
            "macos": (".zip", ".dmg"),
            "linux": (".tar.gz", ".AppImage"),
        }[manifest["platform"]]
        if set(manifest["artifacts"]) != {stem + ext for ext in extensions}:
            raise ValueError(f"Unexpected package filenames: {target}")
        for suffix in ("smoke", "native-smoke"):
            report = json.loads(
                (path.parent / f"{stem}-{suffix}.json").read_text(encoding="utf-8")
            )
            if report.get("ok") is not True or report.get("version") != APP_VERSION:
                raise ValueError(f"Smoke test not verified: {target}/{suffix}")
        for name, expected in manifest["artifacts"].items():
            asset = path.parent / name
            with asset.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError(f"Package checksum mismatch: {name}")
            hashes[name] = actual
            assets.append(asset.resolve())
        builds.append(manifest)
    if targets != TARGETS:
        raise ValueError(f"Missing build targets: {sorted(TARGETS - targets)}")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)),
        encoding="utf-8",
    )
    information = output / "BUILDINFO.json"
    information.write_text(
        json.dumps(builds, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    base = f"https://github.com/{repository}/releases/download/{tag}"
    rows = [
        ("Windows x64", "windows-x86_64-Setup.exe"),
        ("Mac — Apple Silicon (M-series)", "macos-arm64.dmg"),
        ("Mac — Intel", "macos-x86_64.dmg"),
        ("Linux x64", "linux-x86_64.AppImage"),
        ("Linux ARM64", "linux-arm64.AppImage"),
    ]
    table = "\n".join(
        f"| {label} | [Download]({base}/JumpTrack-{APP_VERSION}-{suffix}) |"
        for label, suffix in rows
    )
    notes = output / "release-notes.md"
    notes.write_text(
        f"# JumpTrack {APP_VERSION}\n\n"
        "First public desktop pre-release. Python and app dependencies are included; no Python installation is needed.\n\n"
        "## Downloads\n\n| Computer | Installer |\n| --- | --- |\n" + table + "\n\n"
        "Portable ZIP and TAR.GZ alternatives are also available under Assets. Download only the package matching your computer. Public release downloads do not require a GitHub account.\n\n"
        "## Features\n\n"
        "- Bluetooth discovery and device selection.\n"
        "- Staged warning/settings edits with explicit Apply and readback.\n"
        "- Jump profiles, deployment altitude and altitude/vertical-speed graphs.\n"
        "- Battery voltage and device-reported status, saved-sound tests, date/time and altitude offset.\n"
        "- Separate confirmations for erase/reset and altitude offset.\n\n"
        "## Testing and limitations\n\n"
        "All five targets passed source tests and packaged demo smoke tests, including their native package wrappers. The owner has tested PROTRACK 3 operation on Linux; Windows/macOS Bluetooth behavior still requires real-machine validation. Other altimeter models remain unverified.\n\n"
        "**Unsigned development builds:** Windows may show a publisher/reputation warning. macOS builds are ad-hoc signed, not Developer ID signed or notarized, and macOS may block them. No OS security bypass or blanket compatibility is implied. Linux CI packages are built on Ubuntu 24.04; older distributions are not guaranteed compatible.\n\n"
        "**Altitude offset:** setting it enters Flight Mode and disables Bluetooth. The tested PROTRACK 3 may require its reset-hole procedure before further use.\n\n"
        f"See [installation instructions](https://github.com/{repository}/blob/{tag}/docs/INSTALLING.md) and the repository's existing unofficial/reference-source and licensing notice. No new license or redistribution rights are granted by this release.\n\n"
        "SHA256SUMS.txt verifies package contents. BUILDINFO.json records the dependency versions and build hosts.\n",
        encoding="utf-8",
    )
    return sorted(assets) + [
        checksums.resolve(),
        information.resolve(),
    ], notes.resolve()


def publish(assets, notes, tag, repository):
    command = ["gh", "release"]
    existing = subprocess.run(
        command + ["view", tag, "--repo", repository, "--json", "isDraft,assets"],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode == 0:
        release = json.loads(existing.stdout)
        if not release["isDraft"]:
            raise ValueError(
                "Release is already public; refusing to replace assets. Use a new version."
            )
        expected = {asset.name for asset in assets}
        if any(asset["name"] not in expected for asset in release["assets"]):
            raise ValueError("Draft has unexpected assets; refusing to publish them")
        subprocess.run(
            command
            + [
                "edit",
                tag,
                "--repo",
                repository,
                "--title",
                f"JumpTrack {APP_VERSION}",
                "--notes-file",
                str(notes),
                "--prerelease",
            ],
            check=True,
        )
    else:
        subprocess.run(
            command
            + [
                "create",
                tag,
                "--repo",
                repository,
                "--verify-tag",
                "--draft",
                "--prerelease",
                "--title",
                f"JumpTrack {APP_VERSION}",
                "--notes-file",
                str(notes),
            ],
            check=True,
        )
    # Upload to a draft first so public downloads never appear half-complete.
    subprocess.run(
        command + ["upload", tag, "--repo", repository, "--clobber", *map(str, assets)],
        check=True,
    )
    uploaded = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repository}/releases?per_page=100",
            "--paginate",
            "--jq",
            f".[] | select(.tag_name == {json.dumps(tag)})",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    uploaded_release = json.loads(uploaded.stdout)
    if not uploaded_release.get("draft"):
        raise ValueError("Release is no longer a draft; refusing to modify it")
    if {item["name"] for item in uploaded_release["assets"]} != {
        asset.name for asset in assets
    }:
        raise ValueError("Uploaded release asset list is incomplete")
    remote = {item["name"]: item for item in uploaded_release["assets"]}
    for asset in assets:
        with asset.open("rb") as stream:
            digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        if (
            remote[asset.name]["size"] != asset.stat().st_size
            or remote[asset.name].get("digest") != digest
        ):
            raise ValueError(
                f"Uploaded asset failed size/hash verification: {asset.name}"
            )
    subprocess.run(
        command + ["edit", tag, "--repo", repository, "--draft=false", "--prerelease"],
        check=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the verified files as a public pre-release",
    )
    args = parser.parse_args(argv)
    assets, notes = prepare_release(args.artifacts, args.output, args.tag, args.repo)
    print(f"Verified {len(assets)} release assets; notes: {notes}")
    if args.publish:
        publish(assets, notes, args.tag, args.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
