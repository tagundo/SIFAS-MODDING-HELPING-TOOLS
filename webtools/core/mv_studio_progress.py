"""Progress events and cancellation for an MV Studio game import.

``load_game(..., on_progress=callback)`` calls ``callback(event)`` on the
import thread with small JSON-ready dicts:

- ``{"type": "plan", "v": 1, "members": N, "bytes": B, "steps": [...]}``
  once, right after the game catalog is resolved. Each step has an ``id``,
  a relative weight ``w`` (expected seconds of a first import, in tenths), an
  English ``label`` that the page translates, and, where known, the bytes
  of game data it reads. Member steps also carry ``index``, ``of`` and
  ``name``.
- ``{"type": "progress", "step": id, "state": "start" | "done" | "cached" |
  "skipped" | "failed"}`` whenever a step changes state (``cached``: reused
  without converting). Member steps repeat ``index`` and ``of``.
- ``{"type": "progress", "step": id, "phase": name, "done": k, "total": n}``
  while a step works (``bundle``, ``tracks``, ``effects`` of the timeline;
  ``motion``, ``textures``, ``animation`` of a member), at most every
  ``interval`` seconds.

Every event carries ``t`` (seconds since the import started) and ``read``
(game data bytes read so far). The callback may raise ImportCancelled, a
BaseException, so the converters' ``except Exception`` recovery cannot
swallow it; the import then unwinds and caches nothing of the partial work.

Between events the callback also receives ``None`` (at most every
``interval`` seconds): nothing to report, only the chance to raise
ImportCancelled. Every deadline check of the converters is such a point
(``alive()``), so an import stops soon after its client leaves, also in
the middle of a long step.

Converters deep inside the import report through ``tick()`` and ``alive()``.
They only do something on the thread that runs an import with progress, so
other tools that share those converters are unaffected.
"""
from contextlib import contextmanager
import threading
import time


class ImportCancelled(BaseException):
    """The client stopped waiting for this import."""


LABELS = {
    "resolve": "Reading game data…",
    "timeline": "Reading the live timeline…",
    "stage": "Converting the stage…",
    "effect": "Converting stage effects…",
    "props": "Converting stage props…",
    "member": "Converting member {index}/{count}: {name}",
    "audio": "Decoding the soundtrack…",
    "finish": "Finishing the MV project…",
}
# Tenths of a second a first (uncached) import spends in each step on a desktop.
WEIGHTS = {"resolve": 3, "timeline": 20, "stage": 12, "effect": 16, "props": 3, "member": 35, "audio": 5, "finish": 2}
_STATES = {"start", "done", "cached", "skipped", "failed"}
_LOCAL = threading.local()


class Progress:
    def __init__(self, callback, *, interval=.15, clock=time.monotonic):
        if not callable(callback):
            raise TypeError("The progress callback must be callable.")
        self._callback, self._interval, self._clock = callback, interval, clock
        self._started = clock()
        self._next = 0.
        self._next_check = 0.
        self._read = 0
        self._current = None
        self._thread = threading.get_ident()

    def _emit(self, event):
        event["t"] = round(self._clock() - self._started, 2)
        event["read"] = self._read
        self._next = self._clock() + self._interval
        self._callback(event)

    def plan(self, steps, members, total_bytes):
        rows = []
        for step in steps:
            row = {"id": step["id"], "w": WEIGHTS[step["id"]], "label": LABELS[step["id"]]}
            row.update({key: step[key] for key in ("bytes", "index", "of", "name") if step.get(key) is not None})
            rows.append(row)
        self._emit({"type": "plan", "v": 1, "members": members, "bytes": total_bytes, "steps": rows})

    def read(self, count):
        self._read += max(0, int(count))

    def state(self, step, state, **ids):
        if step not in LABELS or state not in _STATES:
            raise ValueError("Unknown MV import progress step.")
        self._current = (step, ids) if state == "start" else None
        self._emit({"type": "progress", "step": step, "state": state, **ids})

    @contextmanager
    def step(self, step, **ids):
        """Report start, then done (or the state the body stores in ``outcome[0]``), or failed."""
        outcome = ["done"]
        self.state(step, "start", **ids)
        try:
            yield outcome
        except Exception:
            self.state(step, "failed", **ids)
            raise
        self.state(step, outcome[0], **ids)

    def phase(self, phase):
        """A new phase of the current step: always reported."""
        self.tick(phase, force=True)

    def alive(self):
        """Let the callback stop the import here (it receives None), at most every interval."""
        now = self._clock()
        if now < self._next_check or threading.get_ident() != self._thread:
            return
        self._next_check = now + self._interval
        self._callback(None)

    def tick(self, phase, done=None, total=None, force=False):
        if threading.get_ident() != self._thread or (not force and self._clock() < self._next):
            return
        step, ids = self._current or (None, {})
        event = {"type": "progress", "step": step, "phase": phase, **ids}
        if done is not None:
            event["done"] = done
        if total is not None:
            event["total"] = total
        self._emit(event)


class _Silent:
    """The Progress interface for an import nobody watches."""

    def plan(self, steps, members, total_bytes):
        pass

    def read(self, count):
        pass

    def state(self, step, state, **ids):
        pass

    @contextmanager
    def step(self, step, **ids):
        yield ["done"]

    def phase(self, phase):
        pass

    def alive(self):
        pass

    def tick(self, phase, done=None, total=None, force=False):
        pass


SILENT = _Silent()


def activate(progress):
    """Let converters on this thread report into ``progress``; returns what restore() needs."""
    previous = getattr(_LOCAL, "progress", None)
    _LOCAL.progress = None if progress is SILENT else progress
    return previous


def restore(previous):
    _LOCAL.progress = previous


@contextmanager
def active(progress):
    previous = activate(progress)
    try:
        yield progress
    finally:
        restore(previous)


def tick(phase, done=None, total=None, force=False):
    progress = getattr(_LOCAL, "progress", None)
    if progress is not None:
        progress.tick(phase, done, total, force)


def alive():
    """A cancellation point for converters: cheap, and a no-op outside an import with progress."""
    progress = getattr(_LOCAL, "progress", None)
    if progress is not None:
        progress.alive()
