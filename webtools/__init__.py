"""webtools - a local-first WebUI over the existing SIFAS modding CLI tools.

This package is purely additive: it imports the *existing* pure-core functions
from the tool scripts at the repo root (no logic is duplicated) and serves a
small browser UI from Python's standard library (no third-party web framework,
so `python -m webtools` runs on a bare Termux/PC/Mac with only UnityPy present).
"""

__version__ = "0.1.0"
