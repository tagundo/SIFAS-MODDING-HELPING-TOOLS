"""Locate the modding-tools repo root and put it on sys.path so the adapters can
`import sifas_breast_tuner` / `import skirt_length_changer` directly."""
import sys
from pathlib import Path


def repo_root() -> Path:
    # webtools/core/repo.py -> parents[0]=core, [1]=webtools, [2]=repo root
    return Path(__file__).resolve().parents[2]


def ensure_repo_on_path() -> str:
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    return root
