"""Isolated format65 codec bounds, channel/alpha parity and immutable cache.

The native fixture is independently authored and encoded; its golden pixels
come from host UnityPy, not this CLI. An APK/Mac test supplies its bundled CLI;
an ordinary host builds the same pinned scalar source when a compiler exists.
"""
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import decode

try:
    from PIL import Image
except ImportError:
    Image = None

RESOURCE = Path(decode.__file__).parent / "resources/texture65_decoder"
FIXTURE = RESOURCE / "fixtures/neutral65.crn"
GOLDEN = RESOURCE / "fixtures/neutral65.json"
MIP_FIXTURE = RESOURCE / "fixtures/neutral65-mips.crn"
MIP_GOLDEN = RESOURCE / "fixtures/neutral65-mips.json"


class Texture:
    def __init__(self, raw=b"", width=2, height=2, **values):
        self.m_Width, self.m_Height = width, height
        self.m_TextureFormat = 65
        self.m_ImageCount, self.m_TextureDimension = 1, 2
        self.m_ColorSpace = 0
        self.m_Name = "neutral"
        self.m_MipCount = 1
        self.m_TextureSettings = SimpleNamespace(m_FilterMode=1)
        self.m_StreamData = None
        self.image_data = self.data = raw
        self.reads = 0
        self.__dict__.update(values)

    def get_image_data(self):
        self.reads += 1
        return self.data

    @property
    def image(self):
        raise AssertionError("App Python must not enter Texture2D.image")


def enum(value):
    names = {65: "ETC2_RGBA8Crunched", 64: "ETC_RGB4Crunched"}
    return SimpleNamespace(name=names.get(value, value))


class DecoderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.enums = patch.dict(sys.modules, {"UnityPy.enums": SimpleNamespace(TextureFormat=enum)})
        self.enums.start(); self.addCleanup(self.enums.stop)

    def image(self, texture):
        return decode._android_image(texture, time.monotonic() + 5)

    def test_bounds_and_layout_reject_before_encoded_stream_access(self):
        cases = ({"m_Width": 0}, {"m_Height": True}, {"m_Width": 8193},
                 {"m_Width": 4097, "m_Height": 4096}, {"m_ImageCount": 2},
                 {"m_TextureDimension": 3}, {"object_reader": SimpleNamespace(platform=11)},
                 {"object_reader": SimpleNamespace(platform=38), "m_PlatformBlob": [1]},
                 {"m_StreamData": SimpleNamespace(size=decode._MAX_SOURCE_BYTES+1)},
                 {"_texture65_mip": True}, {"_texture65_mip": -1},
                 {"_texture65_source_width": 0},
                 {"_texture65_source_width": 4, "_texture65_source_height": 4},
                 {"m_TextureFormat": 64})
        with patch.object(decode.subprocess, "run") as run:
            for changes in cases:
                texture = Texture(**changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.image(texture)
                self.assertEqual(texture.reads, 0)
        run.assert_not_called()

    @unittest.skipUnless(Image, "Pillow is required")
    def test_missing_decoder_does_not_enter_optional_native_python_codec(self):
        actual_import = builtins.__import__
        def no_codec(name, *args, **kwargs):
            if name == "texture2ddecoder":
                raise AssertionError("Native Python codec import attempted")
            return actual_import(name, *args, **kwargs)
        with patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": ""}), patch.object(builtins, "__import__", side_effect=no_codec):
            with self.assertRaisesRegex(ValueError, "Bundled UnityCrunch"):
                self.image(Texture(b"not decoded in process"))

    @unittest.skipUnless(Image, "Pillow is required")
    def test_failure_signal_timeout_bad_output_and_recovery_release_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary)/"decoder"; binary.write_bytes(b"fixture")
            texture = Texture(b"encoded bytes")
            def valid(command, **kwargs):
                Path(command[-1]).write_bytes(bytes([1,2,3,4])*4)
                return SimpleNamespace(returncode=0)
            cases = (lambda *a, **k: SimpleNamespace(returncode=-4),
                     lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("codec", 1)),
                     lambda command, **k: (Path(command[-1]).write_bytes(b"bad"), SimpleNamespace(returncode=0))[1])
            with patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": str(binary)}):
                for failure in cases:
                    with self.subTest(failure=failure), patch.object(decode.subprocess, "run", side_effect=failure):
                        with self.assertRaises((ValueError, subprocess.TimeoutExpired)):
                            self.image(texture)
                    with patch.object(decode.subprocess, "run", side_effect=valid):
                        self.assertEqual(self.image(texture).tobytes(), bytes([1,2,3,4])*4)
            self.assertEqual(texture.data, b"encoded bytes")


@unittest.skipUnless(Image, "Pillow is required")
class NativeTexture65Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # patch.dict(sys.modules) restores newly imported modules. Preload
        # NumPy before those per-test boundaries so another viewer test cannot
        # inherit a partially unloaded NumPy extension after this suite.
        if importlib.util.find_spec("numpy") is not None:
            __import__("numpy")
        if not all(path.is_file() for path in (FIXTURE,GOLDEN,MIP_FIXTURE,MIP_GOLDEN)):
            raise AssertionError("The required authored format65 fixtures are missing")
        cls.meta = json.loads(GOLDEN.read_text())
        cls.encoded = FIXTURE.read_bytes()
        cls.mip_meta=json.loads(MIP_GOLDEN.read_text())
        cls.mip_encoded=MIP_FIXTURE.read_bytes()
        selected = os.environ.get("ELICHIKA_TEXTURE65_TEST_BIN") or os.environ.get("ELICHIKA_TEXTURE65_BIN")
        if selected and Path(selected).is_file():
            cls.binary = Path(selected)
        else:
            if not shutil.which("c++"):
                raise unittest.SkipTest("Supply the bundled CLI or a host C++ compiler")
            cls.temporary = tempfile.TemporaryDirectory()
            cls.addClassCleanup(cls.temporary.cleanup)
            cls.binary = Path(cls.temporary.name)/"texture65"
            subprocess.run([sys.executable, str(RESOURCE/"build.py"), "--target", "host", "--output", str(cls.binary)],
                           check=True, stdout=subprocess.DEVNULL, timeout=120)

    def setUp(self):
        self.env = patch.dict(os.environ, {"ELICHIKA_TEXTURE65_BIN": str(self.binary)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.enums = patch.dict(sys.modules, {"UnityPy.enums": SimpleNamespace(TextureFormat=enum)})
        self.enums.start(); self.addCleanup(self.enums.stop)

    def texture(self, **values):
        return Texture(self.encoded, self.meta["width"], self.meta["height"], **values)

    def test_authored_asymmetric_rgba_exact_one_flip_straight_alpha_and_color_space(self):
        self.assertEqual(hashlib.sha256(self.encoded).hexdigest(), self.meta["encoded_sha256"])
        self.assertNotEqual(self.meta["rgba_unflipped_sha256"], self.meta["rgba_display_sha256"])
        original_import=builtins.__import__
        def no_codec(name,*args,**kwargs):
            if name=="texture2ddecoder":raise AssertionError("In-process codec import attempted")
            return original_import(name,*args,**kwargs)
        for space in (0, 1):
            texture = self.texture(m_ColorSpace=space)
            with patch.object(builtins,"__import__",side_effect=no_codec):
                image = decode._android_image(texture, time.monotonic()+10)
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.size, (self.meta["width"], self.meta["height"]))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), self.meta["rgba_display_sha256"])
            self.assertEqual(texture.data, self.encoded)
            self.assertEqual(texture.m_ColorSpace, space)
        from webtools.core import model_materials
        source=Texture(self.mip_encoded,self.mip_meta["width"],self.mip_meta["height"],m_MipCount=self.mip_meta["mip_count"])
        objects=model_materials._original_mips(SimpleNamespace(assets_file=object(),path_id=17),source)
        levels=[source]+[obj.read() for obj in objects]
        self.assertEqual(len(levels),len(self.mip_meta["levels"]))
        self.assertEqual(hashlib.sha256(self.mip_encoded).hexdigest(),self.mip_meta["encoded_sha256"])
        for texture,meta in zip(levels,self.mip_meta["levels"]):
            self.assertEqual(texture.get_image_data(),self.mip_encoded)
            image=decode._android_image(texture,time.monotonic()+10)
            self.assertEqual(image.size,(meta["width"],meta["height"]))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),meta["rgba_display_sha256"])
        self.assertEqual(source.data,self.mip_encoded)
        self.assertEqual(source.m_MipCount,self.mip_meta["mip_count"])

    def test_native_interface_output_length_header_mismatch_crc_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source=root/"in.crn"; output=root/"out.rgba"
            source.write_bytes(self.encoded)
            command=[str(self.binary),str(self.meta["width"]),str(self.meta["height"]),str(source),str(output)]
            subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            raw=output.read_bytes()
            self.assertEqual(len(raw),self.meta["width"]*self.meta["height"]*4)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),self.meta["rgba_unflipped_sha256"])
            self.assertNotEqual(subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode,0)
            self.assertEqual(output.read_bytes(),raw)
            output.unlink()
            corrupted=bytearray(self.encoded);corrupted[-1]^=1;source.write_bytes(corrupted)
            self.assertNotEqual(subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode,0)
            self.assertFalse(output.exists())
            # Header/offset metadata must be rejected before a transcoder can
            # use it to allocate or address bytes. Format14 stays unsupported
            # until an independent conformance sample is added.
            for offset,replacement in ((2,b"\xff\xff"),(6,b"\x7f\xff\xff\xff"),
                                       (16,b"\0"),(17,b"\x06"),(18,b"\x0e"),
                                       (19,b"\0\x01"),(70,b"\xff\xff\xff\xff")):
                changed=bytearray(self.encoded);changed[offset:offset+len(replacement)]=replacement
                source.write_bytes(changed)
                code=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode
                self.assertGreater(code,0)
                self.assertFalse(output.exists())
            source.write_bytes(self.encoded)
            command[1]="0"
            self.assertNotEqual(subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode,0)
            self.assertFalse(output.exists())
            source.write_bytes(self.mip_encoded)
            command=[str(self.binary),str(self.mip_meta["width"]),str(self.mip_meta["height"]),str(source),str(output)]
            for meta in self.mip_meta["levels"]:
                subprocess.run(command+["--mip",str(meta["level"])],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                raw=output.read_bytes();output.unlink()
                self.assertEqual(len(raw),meta["rgba_bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(),meta["rgba_unflipped_sha256"])
            for level in ("-1",str(self.mip_meta["mip_count"]),"99999"):
                self.assertGreater(subprocess.run(command+["--mip",level],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode,0)
                self.assertFalse(output.exists())

    def test_content_decoder_identity_and_reimport_cache_never_publish_failure(self):
        from webtools.core import model_viewer as viewer
        viewer._TEXTURE_PNGS.clear()
        self.addCleanup(viewer._TEXTURE_PNGS.clear)
        texture=self.texture();original_run=decode.subprocess.run
        with patch.object(decode.subprocess,"run",wraps=original_run) as run:
            first=viewer._texture_png(texture,time.monotonic()+10)
            self.assertEqual(viewer._texture_png(self.texture(),time.monotonic()+10),first)
            self.assertEqual(run.call_count,1)
            previous=getattr(viewer._REQUEST_STATE,"reimport",False)
            viewer._REQUEST_STATE.reimport=True
            try:self.assertEqual(viewer._texture_png(self.texture(),time.monotonic()+10),first)
            finally:viewer._REQUEST_STATE.reimport=previous
            self.assertEqual(run.call_count,2)
        with tempfile.TemporaryDirectory() as temporary:
            other=Path(temporary)/"decoder";shutil.copy2(self.binary,other);other.chmod(0o755)
            with patch.dict(os.environ,{"ELICHIKA_TEXTURE65_BIN":str(other)}),patch.object(decode.subprocess,"run",wraps=original_run) as run:
                self.assertEqual(viewer._texture_png(self.texture(),time.monotonic()+10),first)
                self.assertEqual(run.call_count,1)
        bad=bytearray(self.encoded);bad[-1]^=1
        for _ in range(2):
            with self.assertRaises(ValueError):
                viewer._texture_png(Texture(bytes(bad),self.meta["width"],self.meta["height"]),time.monotonic()+10)
        self.assertEqual(texture.data,self.encoded)
        viewer._TEXTURE_PNGS.clear()
        from webtools.core import model_materials
        source=Texture(self.mip_encoded,self.mip_meta["width"],self.mip_meta["height"],m_MipCount=self.mip_meta["mip_count"])
        proxies=model_materials._original_mips(SimpleNamespace(assets_file=object(),path_id=18),source)
        levels=[source]+[obj.read() for obj in proxies]
        with patch.object(decode.subprocess,"run",wraps=original_run) as run:
            pngs=[viewer._texture_png(value,time.monotonic()+10) for value in levels]
            self.assertEqual(run.call_count,len(levels))
            self.assertEqual([viewer._texture_png(value,time.monotonic()+10) for value in levels],pngs)
            self.assertEqual(run.call_count,len(levels))
        # Same target dimensions/source bytes but a different claimed original
        # mip profile must reach header validation instead of a cached level.
        forged=Texture(self.mip_encoded,8,8,_texture65_source_width=32,_texture65_source_height=32,_texture65_mip=2)
        with self.assertRaises(ValueError):viewer._texture_png(forged,time.monotonic()+10)


if __name__ == "__main__":
    unittest.main()
