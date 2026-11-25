"""Count failures that may not happen again, so restart-safe receipts never keep their results.

A conversion often recovers from a failure and still returns a result: a
texture shown as unavailable, a particle template left out for time. When
the failure came from the circumstances of this run (a decoder child killed,
timed out or not started, a busy worker, a time budget, an I/O or memory
error) that result is not a pure function of the inputs, and a later run may
do better. The places that hit such failures call note(). The receipt stores
(mv_studio_import_cache, the actor cache) admit a result only when nothing
was noted while it was computed (Watch).

The count is process wide, so failures on worker threads (mip decodes) count
too. A failure in another tool running at the same time also counts; that
only costs a receipt write, never a wrong result.
"""
import subprocess
import threading

_LOCK = threading.Lock()
_COUNT = 0
# Failures of the machine rather than of the data. TimeoutError is an OSError.
ENVIRONMENT = (OSError, MemoryError, subprocess.SubprocessError)


def note():
    """Record a failure that may not happen again."""
    global _COUNT
    with _LOCK:
        _COUNT += 1


def note_if_environmental(error):
    if isinstance(error, ENVIRONMENT):
        note()


def count():
    return _COUNT


class Watch:
    """Started where a cacheable step starts; ``clean`` says whether nothing was noted since."""

    def __init__(self):
        self.start = _COUNT

    @property
    def clean(self):
        return _COUNT == self.start
