# HCA encoder (port of VGAudio)

`webtools/core/cri_hca_encode.py` is a Python + numpy port of the CRI HCA
encoder in VGAudio by Alex Barney:

- repository: https://github.com/Thealexbarney/VGAudio
- ported commit: `9d8f6ea04c83cccccb3dd7851a631bbd53a8dbbe`
  (2020-11-12, "Fix encoding a partial, final opus frame")
- licence: MIT, kept verbatim in `LICENSE` (copied from that commit)

The source was read at that commit; nothing was ported from memory. Each
ported function in `cri_hca_encode.py` names its upstream file. The files used,
relative to `src/` upstream:

| Upstream file | Ported as |
|---|---|
| `VGAudio/Codecs/CriHca/CriHcaEncoder.cs` | parameters, intensity stereo, scale factors, noise level and evaluation boundary searches, band removal, resolutions, quantisation |
| `VGAudio/Codecs/CriHca/CriHcaPacking.cs` | `CalculateResolution`, frame packing |
| `VGAudio/Codecs/CriHca/CriHcaTables.cs` | generated tables (scaling, step sizes, intensity bounds) |
| `VGAudio.Tests/Formats/CriHca/UnpackedTables.cs` | the packed tables of `CriHcaTables.cs` in plain form (upstream tests assert they are equal) |
| `VGAudio/Codecs/CriHca/CriHcaConstants.cs`, `CriHcaFrame.cs`, `CriHcaChannel.cs` | frame constants, channel types, coded band counts, MDCT scale |
| `VGAudio/Codecs/CriHca/CriHcaKey.cs`, `CriHcaEncryption.cs` | type-56 key tables, frame encryption |
| `VGAudio/Containers/Hca/HcaWriter.cs` | header chunks and header checksum |
| `VGAudio/Utilities/Mdct.cs`, `Crc16.cs`, `BitWriter.cs` | MDCT, CRC-16, MSB-first bit order |

Differences from upstream, all deliberate:

- Only the stock SIFAS music parameters are produced: HCA v2.0, 44 100 Hz,
  stereo, 512-byte frames (VGAudio bitrate 176 400), bands 128/64/64, no HFR,
  encoder delay 128, no loop, cipher type 56. HFR and loop code is not ported
  because these parameters never use it.
- Many frames are processed at once with numpy. The type-4 DCT is the matrix
  form of upstream's `Dct4Slow` reference, folded together with the MDCT
  window; results equal the per-subframe port up to float rounding.
- The bit count for resolutions 8 to 15 tests the exact quantised value instead
  of upstream's dead-zone shortcut, so counted bits always equal packed bits.
- The AFS2 bank subkey rule for the cipher key is the one the bundled decoder
  uses (`core.cri_audio_decode`); SIFAS banks use subkey 0.

Tables are cross-checked against the vendored clHCA decoder
(`../cri_hca/clhca_data.h`, ISC) in `tests/test_cri_hca_encode.py`, and every
registration encode is decoded again through clHCA
(`core.cri_acb_write.verify_cue`).

No game audio is included.
