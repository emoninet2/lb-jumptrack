# Start JumpTrack

The desktop downloads include Python and the application dependencies. You do
not need Python, pip, Git or a terminal for normal Windows/macOS use.

## Choose your download

| Computer | Package |
| --- | --- |
| Windows x64 | `JumpTrack-VERSION-windows-x86_64-Setup.exe` |
| Mac with Apple Silicon (M-series) | `JumpTrack-VERSION-macos-arm64.dmg` |
| Mac with Intel processor | `JumpTrack-VERSION-macos-x86_64.dmg` |
| Linux x64 | `JumpTrack-VERSION-linux-x86_64.AppImage` |
| Linux ARM64 | `JumpTrack-VERSION-linux-arm64.AppImage` |

The actual version replaces `VERSION` in each filename. Windows ARM is not a
native target in the initial build matrix. Packages are desktop applications;
they do not target Android, iOS, or every Linux distribution.

Downloads are produced by the repository's **Desktop packages** GitHub Actions
workflow. Open a completed run and download the artifact for your OS/processor;
extract GitHub's artifact ZIP first to get the installer inside. Downloading
Actions artifacts can require signing in to GitHub. A maintainer can also attach
the resulting packages to a GitHub Release; packaging does not publish a release
automatically. See [maintainer instructions](PACKAGING.md).

## Windows

1. Run the `Setup.exe` file. The installer installs for your user account and
   adds JumpTrack to the Start menu without requiring administrator privileges.
2. Open JumpTrack from Start. An optional desktop shortcut can be selected during
   installation.
3. Alternatively, extract the portable ZIP and open `JumpTrack.exe`. Keep its
   `_internal` directory beside it; do not copy the executable out on its own.

Current packages are unsigned development builds. Windows may show a publisher
or reputation warning. Public distribution should use a trusted signed installer;
signing is not implied by the packaging workflow. Only run downloads you trust.

## macOS

1. Open the DMG for your processor, then drag **JumpTrack.app** onto **Applications**.
2. Open JumpTrack from Applications.
3. Allow Bluetooth access when macOS asks. If access was denied, review JumpTrack
   under **System Settings → Privacy & Security → Bluetooth**.

Current builds are not Developer ID signed/notarized unless a maintainer provides
that configuration. macOS may block an unnotarized downloaded app. Do not disable
Gatekeeper globally; use your organization's trusted testing process, or wait for
a signed release. See Apple's current instructions for opening trusted unsigned
apps in Privacy & Security. ZIP downloads contain the same application bundle.

## Linux

1. Download the AppImage for your processor.
2. In your file manager, open Properties/Permissions and enable running the file
   as a program. Then open it. Desktop file managers differ; an equivalent command
   is `chmod +x JumpTrack-*.AppImage` followed by running the chosen file.
3. Turn on your computer's Bluetooth adapter. The system must provide BlueZ and
   a working user D-Bus session. Do not run the app with `sudo`.

If the AppImage runtime needs FUSE on your distribution and FUSE is unavailable,
try the documented AppImage `--appimage-extract-and-run` option, or extract the
`.tar.gz` fallback and launch `JumpTrack/JumpTrack`. Keep the extracted folder
together. These packages still rely on compatible system display/graphics and
Bluetooth libraries; bundling Python does not bundle the operating system.
CI Linux packages are built on Ubuntu 24.04; older distributions are not promised
compatible. A locally built package inherits the local build host's requirements.

## Connect to the altimeter

1. Enable Bluetooth on your computer.
2. Open JumpTrack. Enable Bluetooth on the altimeter immediately before scanning,
   because its advertising mode can time out.
3. Click **Scan Bluetooth**, choose your device and click **Connect**. The filter
   matches names or addresses; **All devices** also shows unrecognized devices.
4. Inspect the Overview, Warnings, Logbook and Settings tabs. Changed preferences
   stay local until **Apply changes**.

The screenshots in the README use synthetic data. To explore without hardware,
launch the app executable with `--demo`. Erase/reset and altitude offset have
separate confirmations. Setting an offset intentionally ends the Bluetooth
session; the tested PROTRACK 3 may need its reset-hole procedure afterward.

## Troubleshooting

- **No devices:** check adapter power, Bluetooth permissions, the device's timeout,
  distance, and whether another application holds the device connection.
- **Connection drops:** enable Bluetooth on the altimeter again, then reconnect.
  Pending edits are never automatically sent on reconnection.
- **App fails to start:** packaged launches write `jumptrack.log` under the OS's
  application data directory, including startup errors. Typical locations:
  Windows `%LOCALAPPDATA%\JumpTrack`, macOS `~/Library/Application Support/JumpTrack`,
  Linux `~/.local/share/JumpTrack`. Actual paths follow Qt's platform conventions
  and can vary with XDG/environment configuration. Logs rotate to limit size.
  Review logs before sharing; they can contain device identifiers and responses.

Windows/macOS bundles still require real-machine Bluetooth validation. A successful
packaged demo smoke test verifies dependencies, UI and shared behavior, not the
computer's Bluetooth hardware or permissions.

## Updating

Close JumpTrack before updating. On Windows, run the new installer for the same
user account. On macOS, replace the old application with the new one. On Linux,
replace the AppImage. For portable ZIP/TAR.GZ downloads, extract into a fresh folder
rather than merging into an old bundle. Keep any profiles you exported separately.
Updating the computer application does not update firmware or write device settings.
