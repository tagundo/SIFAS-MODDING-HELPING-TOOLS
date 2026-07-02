"""A tiny in-process job manager that bridges the tools' callback contract
(on_log / on_progress / should_stop) to a Server-Sent-Events stream.

Events are buffered in a list (not just a Queue) so a client that connects to
the SSE stream slightly after the job starts still replays every event from the
beginning - nothing is lost, and the stream can be reopened.
"""
import threading
import time
import traceback
import uuid


class Job:
    def __init__(self, job_id: str, tool_id: str):
        self.id = job_id
        self.tool_id = tool_id
        self.status = "queued"            # queued | running | done | error | cancelled
        self.cancel_event = threading.Event()
        self._events = []                 # list of dicts
        self._cond = threading.Condition()
        self._done = False
        self._t0 = time.monotonic()       # for the [+s] elapsed stamp on log lines

    # ---- producer side (called from the worker thread / tool callbacks) ----
    def emit(self, event: dict):
        with self._cond:
            self._events.append(event)
            if event.get("type") == "done":
                self._done = True
            self._cond.notify_all()

    def elapsed(self):
        return time.monotonic() - self._t0

    def log(self, line):
        # stamp each line with the time since the job started, so a slow stage is
        # obvious from the gap between consecutive lines (the WebUI has no other
        # way to show where the time goes on a long mobile run).
        self.emit({"type": "log", "line": f"[+{self.elapsed():5.1f}s] {line}"})

    def progress(self, done, total):
        try:
            self.emit({"type": "progress", "done": int(done), "total": int(total)})
        except (TypeError, ValueError):
            pass

    def should_stop(self) -> bool:
        return self.cancel_event.is_set()

    # ---- consumer side (called from the SSE handler) ----
    def event_at(self, index: int, timeout: float):
        """Return the event at `index`, blocking up to `timeout` seconds for it.
        Returns None if it times out or the job finished with no event there."""
        with self._cond:
            while index >= len(self._events):
                if self._done:
                    return None
                if not self._cond.wait(timeout=timeout):
                    return None
            return self._events[index]

    @property
    def event_count(self) -> int:
        with self._cond:
            return len(self._events)

    @property
    def is_done(self) -> bool:
        return self._done


class JobManager:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def create(self, tool_id: str) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, tool_id)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str):
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job:
            job.cancel_event.set()
            return True
        return False

    def run_async(self, job: Job, fn):
        """Run fn(job) on a daemon thread. fn may return a summary string."""
        def runner():
            job.status = "running"
            try:
                summary = fn(job) or ""
                took = f"(took {job.elapsed():.1f}s)"
                summary = f"{summary} {took}".strip() if summary else took
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.emit({"type": "done", "status": "cancelled", "summary": summary})
                else:
                    job.status = "done"
                    job.emit({"type": "done", "status": "done", "summary": summary})
            except Exception as exc:  # noqa: BLE001 - surface any tool error to the UI
                job.status = "error"
                job.emit({"type": "log", "line": f"ERROR: {exc}"})
                job.emit({"type": "log", "line": traceback.format_exc()})
                job.emit({"type": "done", "status": "error", "summary": str(exc)})

        thread = threading.Thread(target=runner, name=f"job-{job.id}", daemon=True)
        thread.start()
        return thread


# A single shared manager for the process.
MANAGER = JobManager()
