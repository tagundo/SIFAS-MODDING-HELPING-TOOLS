"""Locations for derived viewer files and exact legacy-cache scan boundaries.

This module never moves, deletes, or trusts a cache file. Legacy readers must
still validate their own source/selection receipt and payload SHA256 before use.
"""
import os
from pathlib import Path

from .sukusta import default_sukusta_dir


def _absolute(path):
    # Preserve lexical cache boundaries: a symlink alias must not turn an
    # unrelated user folder elsewhere into an automatically ignored tree.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def viewer_cache_root(library_root=None):
    base = Path(default_sukusta_dir("") if library_root is None else library_root).expanduser().resolve()
    return base / "cache" / "viewer"


def game_models_dir(library_root=None):
    return viewer_cache_root(library_root) / "game-models"


def game_motions_dir(library_root=None):
    return viewer_cache_root(library_root) / "game-motions"


def legacy_viewer_cache_roots(extracted_root=None):
    extracted = _absolute(default_sukusta_dir("extracted") if extracted_root is None else extracted_root)
    return (extracted / "game-models", extracted / "game-motions")


def is_legacy_viewer_cache_path(path, extracted_root=None):
    candidate = _absolute(path)
    return any(candidate == root or candidate.is_relative_to(root)
               for root in legacy_viewer_cache_roots(extracted_root))


def prune_legacy_viewer_cache_dirs(directory, dirs, extracted_root=None):
    """Prune only the configured old generated trees during automatic walks."""
    dirs[:] = [name for name in dirs
               if not is_legacy_viewer_cache_path(Path(directory) / name, extracted_root)]


def legacy_cache_roots(output_root, kind):
    """Read-only fallback locations for a canonical new cache location.

    Arbitrary output folders named game-models do not imply a legacy sibling.
    Readers decide whether a receipt is trustworthy; linked old caches are not
    followed and a missing/invalid receipt requires fresh derivation.
    """
    suffixes = {"models": ("game-models",), "motions": ("game-motions",),
                "audio": ("game-motions", "audio")}
    output = _absolute(output_root)
    suffix = suffixes[kind]
    if kind == "models" and output.name == "transplant-bodies":
        suffix = (*suffix, "transplant-bodies")
    tail = ("cache", "viewer", *suffix)
    if len(output.parts) <= len(tail) or output.parts[-len(tail):] != tail:
        return ()
    library = output.parents[len(tail) - 1]
    legacy = library / "extracted" / Path(*suffix)
    if legacy.is_symlink() or legacy.resolve() != legacy or not legacy.is_dir():
        return ()
    return (legacy,)


def source_walk(root):
    """Walk automatic inputs; an explicitly chosen legacy root stays usable."""
    # Preserve callers' relative paths for relative_to/output mirroring.
    root = Path(root).expanduser()
    explicit_legacy_root = is_legacy_viewer_cache_path(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        if not explicit_legacy_root:
            prune_legacy_viewer_cache_dirs(directory, dirs)
        yield directory, dirs, files


def iter_source_files(root):
    """Yield files from the shared recursive source boundary."""
    root = Path(root).expanduser()
    if root.is_file():
        yield root
        return
    for directory, _, files in source_walk(root):
        for name in files:
            path = Path(directory) / name
            if path.is_file():
                yield path
