# JumpTrack Desktop

The desktop app uses the existing BLE client and app-derived profile decoder.
It adds a local draft of settings; editing a control never sends a command.

## Install and launch

```bash
.venv/bin/python -m pip install -r requirements-gui.txt
.venv/bin/python jumptrack_gui.py
# Explore synthetic data without Bluetooth or device writes:
.venv/bin/python jumptrack_gui.py --demo
```

The optional dependency is PySide6-Essentials (Qt Widgets); CLI users do not need
it. Matplotlib provides the embedded graph and pan/zoom/export toolbar. Bluetooth
runs on a dedicated asyncio thread so requests do not block the interface.

## Connect and inspect

1. Enable Bluetooth on the device immediately before scanning.
2. Click **Scan Bluetooth**, choose the device and click **Connect**.
3. The app reads device information, jump counter/list, warnings, speed units,
   and settings groups 40–42. R-00 also supplies distance units, total freefall
   time and battery information where present.
4. Open **Warnings**, **Logbook**, **Settings**, or **Diagnostics**.

Overview shows battery voltage alongside the status code reported by the device:
**Full** (green), **Half** (yellow), **Almost empty** (orange), or **Critical**
(red). Missing or unrecognized status is shown as **Unknown** in grey. These
are the four battery levels used by the Android app, not percentage estimates.
The original response remains available in Diagnostics and the battery tooltip.

Scan filters match name/address. **All devices** includes unrecognized names;
recognition is not a guarantee of firmware compatibility. Devices do not connect
or change settings merely because they appear in the scan list.

An unavailable or unrecognized settings group is disabled rather than populated
with assumed defaults. For example, the tested PROTRACK 3 returns no W-42 record;
its display controls remain unavailable. Diagnostics preserves raw responses and
read errors locally. A timeout or corrupt transfer stops the read sequence;
it does not deliberately close an established connection. The app does not
automatically reconnect or retry. Successful Apply operations keep the same
Bluetooth session open until Disconnect or closing the app. The hardware can
still terminate its own connection.

## Edit and apply

- Edit controls freely: changed fields become amber and the footer counts
  unsaved changes. **Discard changes** restores the loaded values without writes.
- **Apply changes** first reloads current settings, without downloading the
  logbook again or probing settings groups already reported as unavailable.
  If an edited value has
  changed externally, no writes are sent; the pending values remain for review.
- Affected settings groups are written together, preserving other freshly read
  fields. Warning banks, sound settings, active banks and units use their existing
  supported client methods. Only changed operations are sent.
- Each operation is followed by a fresh read. Confirmed values leave the pending
  draft; mismatches stop the remaining plan. There is no automatic rollback or
  retry. A failure can leave some changes applied, and the UI reports uncertainty.
- If Apply cannot verify a write, the GUI makes one read-only settings recovery
  attempt. It never resends the write automatically. Confirmed edits lose their
  highlights; remaining edits stay local and can be reviewed before another Apply.
  If that read also fails, use Reload to recover without reconnecting.
  The connection stays open if the hardware is still connected. If the radio
  disconnects, reconnect to inspect the actual device. Local
  drafts are not silently sent on reconnect, device switching, or shutdown.
- Reconnecting to the same device preserves pending edits for review and never
  sends them automatically. Reload preserves pending edits and reconciles them
  against freshly read values. Disconnect, switching devices and closing
  require explicit discard when edits are pending. Closing is blocked while an
  operation is in progress.

Warnings display values in the device's loaded distance units without applying
implicit conversion. Distance-unit and warning edits must be applied separately.
An external unit change also blocks pending warning-bank writes until reviewed.

Each warning tab has **Test saved sound**, using the APK's category-specific W-19
command. It plays on the altimeter with its saved pitch and volume; it does not
play computer audio or save settings. Apply pending pitch/volume edits for that
category before testing. Other local drafts remain untouched. The GUI reserves
the connection for the APK's 25-second playback window, disabling conflicting
operations until it ends. Submission does not verify that audible sound occurred;
listen on the device. The command is sent once without waiting for EOF and is
never retried automatically. Demo mode simulates this without sound or Bluetooth.

## Logbook

Select a jump to download and cache its checked raw profile. The information
panel includes date, recorded exit/deployment altitudes, freefall time and stored
speed summaries. The graph shows altitude and derived vertical speed over time,
with the recorded deployment altitude marked. The unit selectors affect only
the displayed graph and export, not device settings.

The Matplotlib toolbar supports pan, zoom and image export. **Export JSON** saves
the decoded profile and explicit units. **Open saved profile** works without a
device and requires valid checksum metadata. Device switching clears the profile
cache. TAS/SAS recording mode remains explicitly unknown; this GUI does not
invent an airspeed-mode flag or label derived vertical speed as confirmed SAS.

## Date/time and altitude offset

Settings includes separate actions for these commands. Apply or discard ordinary
pending edits first; neither action is part of the staged Apply plan.

- **Device date and time:** choose a local wall-clock value or **Sync with computer
  now**. The app sends W-18 once, reads R-00, and verifies the reported clock within
  five seconds. The last-read clock is displayed as a snapshot, not a running clock.
- **Altitude offset:** displays the signed W-17 value from R-00 in the device's
  loaded distance units. The new value is limited to ±9,900 feet or ±3,000 metres,
  matching the Android app's limits. Units are checked again before sending.
  Setting it requires acknowledgement and the exact phrase `SET OFFSET`.

The APK states that setting an offset enters Flight Mode, disables Bluetooth,
and retains the offset for 14 hours if no jump occurs. The user's PROTRACK 3 also
became unavailable until its reset-hole procedure was performed. The GUI explains
this before sending. It sends W-17 once without waiting for EOF, closes the session,
and reports submission rather than claiming verified application. There is no
automatic retry or immediate readback; reconnect later to inspect the actual offset.

## Destructive actions

**Maintenance** is separate from ordinary settings. Buttons are disabled while
settings edits are pending. The dialog identifies the connected device, requires
an acknowledgement checkbox, and requires the exact action-specific phrase:

| Action | Required phrase |
| --- | --- |
| Erase entire logbook | `ERASE LOGBOOK` |
| Restore factory settings | `FACTORY RESET` |

Cancel is the default; whitespace, a partial phrase or an unchecked acknowledgement
keeps confirmation disabled. The backend independently checks the phrase and device
identity before enabling destructive permission for that operation only. It then
disconnects, even on failure. A timeout is reported as potentially applied, with
no retry. Reconnect to inspect the actual outcome.

Individual jump deletion is disabled: no verified single-jump delete command has
been found. The GUI does not substitute a full-logbook erase for that action.

## Scope and validation

The UI covers the supported preferences and warning-bank workflow; advanced CLI
operations such as counter replacement
and direct Java calls remain CLI-only. This GUI is not a full replica of the
Android app. Existing model/firmware and decoder limitations still apply.

Tests exercise the session layer using an in-memory device and Qt interactions
using the offscreen platform. They include stale values, unit conflicts, partial
failure, readback mismatch, typed destructive confirmations and unexpected radio
disconnection. Demo mode uses only synthetic data and never creates a BLE client.
Live GUI operation and writes require user hardware validation; no device was
connected or modified while developing/testing the GUI.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_gui_backend tests.test_gui_window -v
```
