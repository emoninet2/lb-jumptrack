# PROTRACK 3 hardware observations

These observations describe the tested device, not a protocol specification or
compatibility guarantee for other firmware/models. Raw personal captures remain
under the ignored `jumptrack_data/` directory.

## TAS/SAS comparison

On 2026-10-18 the user manually selected TAS and SAS on the device. In each mode,
the client requested every two-digit read number from `R-00` through `R-99`.
All 100 requests in each scan completed with EOF. No configuration commands were
sent by the client.

Ten requests returned payload data:

| Request | Observed content |
| --- | --- |
| `R-00` | Warning configuration, units, clock, totals, battery and other records |
| `R-16` | Feet/meters selection |
| `R-18` | Device clock |
| `R-21` | Record labelled `Temp.-Meter-Feet.-MBar*10` |
| `R-24` | Record labelled `Feet = 0; Meter = 1` |
| `R-37` | Accumulated freefall time |
| `R-38` | mph/kmh selection |
| `R-39` | Jump counter |
| `R-40` | ProTrack options group 1 |
| `R-41` | All options group 1 |

The other 90 returned only echo, checksum metadata and EOF. In particular,
`R-42` returned no W-42 data record on this device.

After ignoring checksum metadata and blank-line framing, 97 responses were
identical across modes. Differences in R-00/R-18 were confined to the clock;
R-21's first field changed from 00236 to 00237. No field tracked TAS/SAS.
This covers two-digit R commands only. Another command format, initialization
sequence or device-local display preference remains possible.

R-38 succeeded in these scans and earlier paired reads. A previous session timed
out; that historical timeout does not establish that the command is unsupported.

## Other observations

Earlier read-only testing confirmed device information, jump counter/list,
warning records, R-40/R-41 records and hex profiles on PROTRACK 3 firmware 01.04.
ACC requests for one tested jump/time range completed without sample data;
ACC retrieval is not verified. Configuration writes, alarm playback and resets
remain unverified on hardware. A separate user test confirmed power-off without
an EOF response.
