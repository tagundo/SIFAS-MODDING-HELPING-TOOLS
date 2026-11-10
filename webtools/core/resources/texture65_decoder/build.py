"""Build the pinned scalar texture65 executable without Python native codecs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ANDROID = {"arm64-v8a": ("aarch64-linux-android24-clang++", 183),
           "x86_64": ("x86_64-linux-android24-clang++", 62)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    if manifest["commit"] != "3ebc3b758bd6b1a3108b50148f7998ee34f058c6":
        raise ValueError("The texture decoder source pin changed.")
    for name, expected in manifest["files"].items():
        path = ROOT / name
        if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT)
                or sha(path) != expected):
            raise ValueError("A pinned texture decoder source/license changed: " + name)
    return {**manifest, "wrapper_sha256": sha(ROOT / "texture65.cpp"), "build_helper_sha256": sha(Path(__file__))}


def elf_layout(raw, machine):
    if raw[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", raw, 16) != (3, machine):
        raise ValueError("Expected a little-endian PIE decoder for the requested ABI.")
    offset = struct.unpack_from("<Q", raw, 32)[0]
    stride, count = struct.unpack_from("<HH", raw, 54)
    segments, interpreter = [], False
    for index in range(count):
        kind, flags, position, address, physical, size, memory, alignment = struct.unpack_from("<II6Q", raw, offset + stride * index)
        if kind == 3:
            interpreter = True
        if kind == 1:
            if alignment < 16384 or address % 16384 != position % 16384:
                raise ValueError("The decoder is not Android 16KB-compatible.")
            segments.append({"offset": position, "address": address, "alignment": alignment,
                             "memory_size": memory, "writable": bool(flags & 2)})
    if not segments or not interpreter:
        raise ValueError("The decoder must be an executable PIE, not a loadable Python library.")
    return segments


def build(target, output, *, ndk=None, abi="arm64-v8a", cxx=None):
    provenance = sources()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    arguments = ["-std=c++17", "-O2", "-DNDEBUG", "-fno-strict-aliasing", "-fms-extensions",
                 "-ffunction-sections", "-fdata-sections", "-fno-ident"]
    if target == "android":
        if ndk is None:
            raise ValueError("Select an Android NDK.")
        host = "darwin" if sys.platform == "darwin" else "linux"
        toolchains = list((Path(ndk).resolve() / "toolchains/llvm/prebuilt").glob(host + "-*"))
        if len(toolchains) != 1:
            raise ValueError("Select a complete Android NDK for this build host.")
        compiler, machine = ANDROID[abi]
        compiler = str(toolchains[0] / "bin" / compiler)
        strip = [str(toolchains[0] / "bin/llvm-strip"), "--strip-all"]
        arguments += ["-fPIE", "-pie", "-static-libstdc++", "-Wl,--gc-sections",
                      "-Wl,-z,max-page-size=16384", "-Wl,-z,common-page-size=16384", "-Wl,-z,relro,-z,now"]
    elif target == "macos":
        if sys.platform != "darwin":
            raise ValueError("Build the Apple Silicon decoder on macOS.")
        compiler = cxx or subprocess.check_output(["xcrun", "--find", "clang++"], text=True).strip()
        strip = ["xcrun", "strip", "-x"]
        arguments += ["-arch", "arm64", "-mmacosx-version-min=13.0", "-Wl,-dead_strip"]
    else:
        compiler = cxx or os.environ.get("CXX") or shutil.which("c++")
        strip = []
    if not compiler or not Path(compiler).is_file():
        raise ValueError("The selected C++ compiler is unavailable.")
    command = [str(compiler), *arguments, "-I" + str(ROOT / "upstream"),
               str(ROOT / "texture65.cpp"), str(ROOT / "upstream/etc.cpp"), "-o", str(temporary)]
    try:
        subprocess.run(command, check=True)
        if strip:
            subprocess.run([*strip, str(temporary)], check=True)
        raw = temporary.read_bytes()
        segments = elf_layout(raw, machine) if target == "android" else None
        temporary.chmod(0o755)
        temporary.replace(output)
        return {"status": "PASS", "target": target, "abi": abi if target == "android" else None,
                "output": str(output), "bytes": len(raw), "sha256": sha(output),
                "command": command, "sources": provenance, "load_segments": segments,
                "interface": "WIDTH HEIGHT INPUT_CRN OUTPUT_RGBA [--mip N]; unflipped straight RGBA8",
                "capabilities": ["texture65-etc2a-rgba8", "authored-mip-v1"]}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("host", "android", "macos"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ndk", type=Path)
    parser.add_argument("--abi", choices=ANDROID, default="arm64-v8a")
    parser.add_argument("--cxx")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = build(args.target, args.output, ndk=args.ndk, abi=args.abi, cxx=args.cxx)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
