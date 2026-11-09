# HCA audio decoder

The three `clhca` source files are copied unmodified from vgmstream's
`src/coding/libs/` directory, retrieved 2026-11-09, commit
`6802153425adde134e49394fc653455166d7d2f2`:
https://github.com/vgmstream/vgmstream/tree/6802153425adde134e49394fc653455166d7d2f2/src/coding/libs

They decode locally held CRI HCA streams, including the game's keyed streams.
The vgmstream ISC license is retained in `LICENSE`; original source attribution
is also retained in `clhca.c`. No game audio is included.

The SIFAS HCA key used by the Python adapter is the public codec key in that
same upstream commit's `src/meta/hca_keys.h` (SIFAS Android entry).

Build the small shared library for the target CPU with its normal C compiler:

```sh
cc -O2 -shared -fPIC clhca.c -o libelichika_hca.so
```

For macOS use `-dynamiclib` and `libelichika_hca.dylib`. Android uses the NDK
compiler and packages the `.so` in the app's native library directory.
`core.cri_audio_decode` loads `ELICHIKA_HCA_LIBRARY`, a library in
`ELICHIKA_NATIVE_DIR`, a library beside these sources, or the app's
`libelichika_hca.so`. FFmpeg is an alternate backend.
