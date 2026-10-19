# Desktop packaging and maintenance

All builds use the same Python sources. There are no Windows, Mac, or Linux
copies of the GUI/session logic. PyInstaller bundles the interpreter, Bleak,
PySide6 and the QtAgg graph dependencies. Build on the target OS/architecture;
this is not cross-compilation from Linux.

## Shared files

| File | Responsibility |
| --- | --- |
| `app_metadata.py` | App name, ID, and version for the GUI, executables, installers and manifests |
| `requirements-build.txt` | Shared pinned direct runtime dependencies and packaging tools |
| `packaging/JumpTrack.spec` | One dependency analysis; QtAgg selection, resources, platform metadata |
| `build_desktop.py` | Build, generate icons, package, smoke-test and checksum artifacts |
| `desktop_entry.py` | Packaged launch, per-user rotating logs, Windows startup and crash handling |
| `desktop_smoke.py` | Hardware-free acceptance test run inside the actual packaged app |
| `packaging/jumptrack.svg` | Editable icon source, rendered into PNG/ICO/ICNS at build time |
| `packaging/windows.iss` | Per-user Windows installer, shortcuts and uninstaller |
| `packaging/appimage-tools.json` | Pinned upstream AppImage tool/runtime URLs and SHA-256 digests |
| `.github/workflows/desktop.yml` | Native OS/architecture CI matrix; tests and downloadable artifacts |
| `publish_release.py` | Verify all build targets, smoke reports and hashes before public pre-release publication |

## Build locally

Use a fresh virtual environment so unrelated Qt bindings and development tools
cannot inflate or contaminate the bundle. CI uses **Python 3.12** on every target.
The ordinary CLI and GUI requirements remain separate from these build tools.

```bash
python -m venv .venv-build
# Activate it using the command for your OS, then:
python -m pip install -r requirements-build.txt
python build_desktop.py
python build_desktop.py --native
```

Without `--native`, output is a portable Windows ZIP, macOS application ZIP or
Linux TAR.GZ. With `--native`, it also creates the Windows installer, macOS DMG,
or Linux AppImage. Native prerequisites:

- **Windows x64:** Inno Setup 6 (`ISCC.exe` on PATH or in its default installation
  directory). The selected hosted runner already includes it. Installation is
  per user, with no administrator elevation.
- **macOS Intel/Apple Silicon:** Apple command-line tools, including `hdiutil`
  and `ditto`. Use the correct native Python architecture. The bundle includes
  `NSBluetoothAlwaysUsageDescription` so CoreBluetooth can request permission.
- **Linux x64/ARM64:** a compatible glibc-based desktop system, Qt display
  libraries and network access for the pinned AppImage tool/runtime. Those
  downloads are checksum verified before use and cached under `build/tools`.
  They are run without requiring FUSE during packaging. Runtime/tool downloads
  are from fixed releases, not mutable `latest` URLs.

Output goes to ignored `build/` and `dist/`. Do not commit binaries or the local
tool cache. Native packages include Python; recipients do not need to install it.
Linux still needs system display/graphics, BlueZ and D-Bus. AppImage is not a
universal compatibility layer: build on the oldest supported distribution and
test on newer ones. CI currently uses Ubuntu 24.04; this local workstation may
produce artifacts requiring a newer glibc than CI artifacts.

The build command runs the bundled executable from a temporary directory outside
the repository, with source-oriented Python environment variables removed. This
checks that a checkout/venv is not accidentally satisfying missing imports. Native
packaging also tests the AppImage, temporarily installs/uninstalls the Windows
installer in a temporary directory, or mounts/tests/detaches the Mac DMG.

## CI and downloading builds

**Desktop packages** runs on pushes to `main`, pull requests, version tags and
manual dispatch. The matrix currently builds:

- Windows x64 on `windows-2022`;
- macOS Apple Silicon on `macos-15` and Intel on `macos-15-intel`;
- Linux x64 on `ubuntu-24.04` and ARM64 on `ubuntu-24.04-arm`.

Each job installs the same requirements, lints/tests the source, builds from the
shared spec, exercises the actual binaries, and uploads packages, checksums,
dependency manifests and JSON smoke reports. A failed test or build fails that
target; the others still finish. Artifacts are retained for 14 days. Failure
reports and packaging logs are uploaded separately. Dependabot checks Python
requirements and pinned GitHub Actions monthly.

The smoke test uses only the in-memory demo: discovery, a session, battery
decoding, profile decoding/rendering, staged edits, apply/readback, simulated
sound playback and worker shutdown. It cannot verify real Bluetooth adapters,
device firmware, radio permissions or OS security prompts. Those require manual
testing on each target OS before calling a release hardware-validated. Source
tests using the optional private Java reference skip in CI when it is absent.

Pushing a matching version tag automatically publishes a **public pre-release**
after all five build jobs pass. Branch/PR/manual runs do not publish releases.
The release job downloads this run's artifacts, verifies their versions, exact
package names, SHA-256 hashes and both smoke reports, then uploads individual
packages to a draft. Only a complete verified upload is made public. It adds a
download table, combined `SHA256SUMS.txt` and `BUILDINFO.json`. Public release
downloads need no GitHub login and do not expire with Actions artifacts.

To distribute a version:

1. Update `APP_VERSION` in `app_metadata.py`; review direct dependency pins when
   needed. The GUI, installer names, version resources and metadata follow it.
2. Commit changes and wait for all five native jobs to pass.
3. Update the README's version-specific download links. Create an annotated
   `v<APP_VERSION>` tag and push it: the workflow rejects mismatched version tags.
4. Wait for the tag's workflow to finish; its final job publishes the pre-release.
   Failures leave no public release or only an unpublished draft. Draft uploads
   can be retried; an already-public release is never overwritten by the helper.
5. Review smoke reports and manually check Bluetooth/OS installation on real
   computers. Signing/notarization and promotion to a stable release remain
   explicit maintainer steps. The current workflow publishes unsigned development
   pre-releases, with their limitations stated in the generated notes.

The release job alone receives `contents: write`; build/PR jobs remain read-only.
It uses GitHub's short-lived Actions token, with no personal token in the repo.
When adding target architectures, update `publish_release.py`'s required target
coverage as well as the workflow matrix so missing packages cannot publish silently.

The build manifest records the actual installed dependency versions and artifact
hashes. Direct dependencies/tools are pinned; transitive dependencies and OS
runner images can still change. This is not a claim of bit-for-bit reproducible
builds. Update dependency pins deliberately and let the matrix validate them.

## Routine code changes

Edit `jumptrack.py`, `gui_backend.py`, `jumptrack_gui.py`, the decoders or other
shared modules normally. Python imports are followed by the same spec on every
OS; ordinary code changes require no installer changes. Add meaningful tests for
behavior changes. If adding dynamically imported modules, native libraries or
non-code assets, declare their collection in the shared spec and extend the
packaged smoke check. Never bundle `jumptrack_data/`, `.jumptrack-address`, secrets,
APK reference files, a developer virtual environment, or private hardware captures.

To add an architecture, first verify dependency wheels and runner availability,
then add a matrix entry. Packaging conventions remain centralized in the builder.
Backend-specific Bluetooth fixes belong in the shared transport/platform boundary,
not copies of the whole app. Bleak remains on the dedicated asyncio thread;
do not use `allow_sta()` to bypass its Windows threading checks.

## Signing and distribution status

The workflow intentionally needs no signing credentials. Windows installers are
unsigned and Mac apps use PyInstaller's default ad-hoc signing; these are development
packages and can trigger OS trust warnings. No signing or notarization success is
implied by a successful build.

For a Developer ID Mac build, the shared spec accepts `JUMPTRACK_CODESIGN_IDENTITY`
in an appropriately configured local/CI keychain. Notarize and staple the final
app/DMG using Apple's tools and verify Gatekeeper behavior before distribution.
Windows Authenticode signing requires a separate protected certificate/provider
and must cover both application binaries and the final installer. If packages
are signed after building, regenerate checksums/manifests for the signed bytes.
Never put private keys or account credentials in the repository or artifacts.

This repository's existing licensing/reference-source status remains unchanged.
Packaging does not grant redistribution rights. Review the repository notice and
applicable third-party license obligations before public redistribution.

## Primary references

- [PyInstaller spec files and macOS metadata](https://pyinstaller.org/en/stable/spec-files.html)
- [PyInstaller Qt/Matplotlib backend collection](https://pyinstaller.org/en/stable/hooks-config.html)
- [Bleak macOS permission metadata](https://bleak.readthedocs.io/en/latest/backends/macos.html)
- [Bleak Windows threading guidance](https://bleak.readthedocs.io/en/latest/troubleshooting.html)
- [GitHub hosted runner images](https://github.com/actions/runner-images)
- [AppImage tooling](https://github.com/AppImage/appimagetool)
