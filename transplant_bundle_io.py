"""Keep expensive bundle compression out of intermediate transplant passes.

The geometry/physics helpers intentionally reopen their completed predecessor.
Their temporary representation can be uncompressed; the published bundle keeps
the wearer's original UnityFS data and block-info compression flags.
"""
import os
from pathlib import Path
import tempfile


def original_packer(bundle):
    if getattr(bundle, "signature", None) == "UnityFS":
        # UnityPy's tuple is passed directly to save_fs(data_flag, block_info_flag).
        return int(bundle.dataflags), int(bundle._block_info_flags)
    return None


def write_working_bundle(bundle, path):
    flags = original_packer(bundle)
    with open(path, "wb") as stream:
        stream.write(bundle.save(packer="none" if flags is not None else "original"))
    return flags


def finish_working_bundle(path, flags):
    if flags is None or flags == (64, 64):
        return
    import UnityPy
    path = Path(path)
    environment = UnityPy.load(str(path))
    encoded = environment.file.save(packer=flags)
    # Final compression cannot leave a truncated output if encoding/writing fails.
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
