# Isolated TextureFormat 65 decoder

This executable restores preview decoding for Unity's
`ETC2_RGBA8Crunched` textures without loading a native codec into the app's
Python process. It transcodes UnityCrunch ETC2A (CRN format 12), then decodes
ETC2 RGBA8. Other Unity/CRN formats are rejected. The default returns the base
mip; `--mip N` returns the original authored level without recompression.

The seven unchanged upstream source files are pinned to
K0lb3/texture2ddecoder commit `3ebc3b758bd6b1a3108b50148f7998ee34f058c6`
(package version 1.0.6). `source-manifest.json` records their hashes.
Retain `LICENSE-MIT`, `LICENSE-Zlib` and the original source notices in every
distribution. The local wrapper/build helper are MIT licensed.

Run `texture65 WIDTH HEIGHT INPUT_CRN OUTPUT_RGBA [--mip N]`, using the original
CRN dimensions. The output is exactly `max(1,width>>N) * max(1,height>>N) * 4`
bytes of unflipped, straight RGBA8 (`N=0` by default). Upstream BGRA bytes are
reordered without premultiplication or gamma conversion. The Python caller
applies Unity's final vertical flip once and preserves source color-space and
material metadata. It never rewrites the original encoded texture.

The wrapper validates dimensions, pixel/input/output limits, one face,
unsegmented CRN layout, mip/header/palette/table offsets and both checksums.
Crunch allocation callbacks enforce a bounded heap budget; fixed buffers are
included in the total memory bound. CPU/file-size/core limits and the parent's
subprocess deadline contain codec failures. Output creation is exclusive and
never follows a symlink. Pixel conversion is scalar and has no optional ISA
requirement.

Build examples:

```
python3 build.py --target host --output /tmp/texture65
python3 build.py --target android --ndk /path/to/ndk --abi arm64-v8a --output /tmp/libelichika_texture65.so
python3 build.py --target macos --output /tmp/texture65
```

Android output is an executable PIE with a static C++ runtime, 16KB-compatible
load segments and only Android system-library dependencies. The `.so` filename
lets Android extract it into `nativeLibraryDir`, like the existing ASTC CLI.
macOS output targets Apple Silicon and macOS 13. Both launchers provide the
trusted absolute executable path through `ELICHIKA_TEXTURE65_BIN`.

Exit codes distinguish invocation/dimension/input/header/checksum/layout,
transcode/pixel decode, output, allocation and process-limit failures. A failed
decode never publishes a successful PNG cache entry.
