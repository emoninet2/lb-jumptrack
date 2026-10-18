# Profile length comparison

Profiles 33 and 34 were downloaded using only `Get Hex Profile in Jump` reads. The connection was then closed. No configuration or deletion commands were sent.

| Jump | Jump-list unknown_1 | Last numeric profile header field | Decoded 16-bit words | Difference |
| --- | --- | --- | --- | --- |
| 33 | 1274 | 1274 | 1273 | 1 |
| 34 | 1393 | 1393 | 1392 | 1 |
| 35 | 1217 | 1217 | 1216 | 1 |

Across all three stored jumps, unknown_1 equals the final numeric profile-header field and is exactly one greater than the raw-word count extracted by the current experimental parser. This strongly supports a profile length/count interpretation. It does not establish whether the count includes a header/reference entry, whether one sample is encoded elsewhere, or whether the parser boundary requires revision. Do not silently drop a word, invent a sample, or rename this as a confirmed sample count without the protocol/response parser.

unknown_2 remains 15360 (0x3C00) for all three jumps. This test does not identify its meaning.
