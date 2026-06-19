"""Headless tkinter stub.

Several tools `import tkinter` at module top level (for their GUI), which would
crash an `import` on a headless server / Termux where tkinter isn't installed.
Their *core* bundle-editing functions never touch tkinter, so we install a
permissive dummy `tkinter` (and submodules) into sys.modules BEFORE importing
such a tool. The GUI code is never called, so the stub is never actually used -
it only lets the module import succeed.

If a real tkinter is importable (desktop with Tk), we leave it alone.
"""
import sys
import types


class _StubMeta(type):
    def __getattr__(cls, name):
        return _Stub

    def __call__(cls, *args, **kwargs):
        return _StubInstance()


class _Stub(metaclass=_StubMeta):
    """Usable as a base class (`class Foo(tk.Frame)`), a callable, and an
    attribute source - whatever the GUI code does at import/class-definition
    time resolves to another _Stub."""
    pass


class _StubInstance:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Stub

    def __call__(self, *args, **kwargs):
        return _StubInstance()

    def __setattr__(self, name, value):
        pass


_SUBMODULES = ("ttk", "filedialog", "messagebox", "font", "colorchooser",
               "simpledialog", "scrolledtext", "constants")


def _stub_getattr(name):
    return _Stub


def ensure_tk_stub():
    """Install a dummy tkinter only if the real one is missing. Idempotent."""
    try:
        import tkinter  # noqa: F401  - real Tk present, nothing to do
        return
    except Exception:
        pass

    existing = sys.modules.get("tkinter")
    if existing is not None and getattr(existing, "_webtools_stub", False):
        return

    mod = types.ModuleType("tkinter")
    mod._webtools_stub = True
    mod.__getattr__ = _stub_getattr
    sys.modules["tkinter"] = mod
    for sub in _SUBMODULES:
        sm = types.ModuleType("tkinter." + sub)
        sm.__getattr__ = _stub_getattr
        sys.modules["tkinter." + sub] = sm
        setattr(mod, sub, sm)
