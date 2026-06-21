"""WebUI access to the shared :mod:`sifas_i18n` module.

``sifas_i18n`` lives at the repository root next to the desktop tools so a single
set of translation tables serves both the GUIs and the WebUI. The root is on
``sys.path`` when the desktop scripts run, but ``python -m webtools`` may be
launched from elsewhere, so make the import robust by adding the repo root first.
"""

import pathlib
import sys

_REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import sifas_i18n as _i18n  # noqa: E402

# re-export the bits the WebUI needs
tr = _i18n.tr
all_strings = _i18n.all_strings
normalize = _i18n.normalize
language_options = _i18n.language_options
SUPPORTED = _i18n.SUPPORTED
LANGUAGE_NAMES = _i18n.LANGUAGE_NAMES
DEFAULT_LANGUAGE = _i18n.DEFAULT_LANGUAGE
