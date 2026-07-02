"""Smoke test for the webtools server that needs no Unity bundle.

Exercises: module imports, the JobManager/SSE event buffering, the HTTP routes,
the jailed file browser (403 on escape), and the full POST-run -> job -> SSE
pipeline (using a missing bundle so the real adapter+core runs and surfaces a
clean error). Run: python -m webtools.selftest
"""
import json
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

FAILS = []


def check(name, cond, detail=""):
    status = "ok " if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def test_imports():
    print("imports:")
    import webtools.server  # noqa: F401
    import webtools.run  # noqa: F401
    from webtools.tools import registry
    check("registry has tools", len(registry.TOOLS) >= 4)
    check("breast_dyna present", registry.get_tool("breast_dyna") is not None)
    # adapters can locate the real import-safe modules + core functions
    from webtools.core.repo import ensure_repo_on_path
    ensure_repo_on_path()
    import sifas_breast_tuner as bt
    import skirt_length_changer as sk
    check("modify_swingbones_in_bundle exists", hasattr(bt, "modify_swingbones_in_bundle"))
    check("modify_livecore_scaling exists", hasattr(bt, "modify_livecore_scaling"))
    check("run_dyna_batch exists", hasattr(bt, "run_dyna_batch"))
    check("modify_skirt_scaling exists", hasattr(sk, "modify_skirt_scaling"))


def test_jobs():
    print("jobs/SSE buffering:")
    from webtools.jobs import JobManager
    mgr = JobManager()
    job = mgr.create("demo")

    def work(j):
        for i in range(1, 4):
            j.log(f"step {i}")
            j.progress(i, 3)
        return "summary-xyz"

    mgr.run_async(job, work).join(timeout=5)
    # replay from index 0 - nothing lost even though we connected "late"
    events, idx = [], 0
    while True:
        ev = job.event_at(idx, timeout=2.0)
        if ev is None:
            break
        events.append(ev)
        idx += 1
        if ev.get("type") == "done":
            break
    types = [e["type"] for e in events]
    check("got progress+log+done", types.count("log") == 3 and types.count("progress") == 3 and types[-1] == "done")
    check("terminal status done", events[-1].get("status") == "done")
    # the manager appends a "(took N.Ns)" timing suffix to the tool's summary
    check("summary propagated", (events[-1].get("summary") or "").startswith("summary-xyz"))


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def _post(url, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_http():
    print("http routes:")
    # jail roots under a temp dir so we can pass an in-root (but missing) bundle
    base = tempfile.mkdtemp(prefix="webtools_selftest_")
    os.environ["SUKUSTA_DIR"] = base
    os.makedirs(os.path.join(base, "extracted"), exist_ok=True)
    os.makedirs(os.path.join(base, "modded"), exist_ok=True)

    from webtools.server import Handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{port}"
    try:
        s, body = _get(root + "/")
        check("GET / 200 + html", s == 200 and b"SIFAS" in body)
        s, body = _get(root + "/static/app.js")
        check("GET /static/app.js 200", s == 200 and b"EventSource" in body)
        s, body = _get(root + "/api/tools")
        check("GET /api/tools", s == 200 and len(json.loads(body)["tools"]) >= 4)
        s, body = _get(root + "/api/fs/roots")
        check("GET /api/fs/roots", s == 200 and "roots" in json.loads(body))

        # jail: a path outside the allowed roots must 403
        try:
            _get(root + "/api/fs/list?path=" + urllib.parse.quote("/etc"))
            check("jail blocks /etc", False, "expected 403")
        except urllib.error.HTTPError as e:
            check("jail blocks /etc", e.code == 403)

        # full run pipeline with a missing (but in-root) bundle -> clean error
        in_path = os.path.join(base, "extracted", "does_not_exist.bundle")
        out_dir = os.path.join(base, "modded")
        s, resp = _post(root + "/api/run/breast_dyna",
                        {"mode": "single", "in_path": in_path, "out_dir": out_dir,
                         "patterns": "LeftBreast_Dyna", "suffix": "_mod"})
        check("POST run returns job_id", s == 200 and "job_id" in resp, str(resp))
        job_id = resp.get("job_id")
        # read the SSE stream to completion
        got_done, status = False, None
        with urllib.request.urlopen(root + f"/api/jobs/{job_id}/events", timeout=10) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    ev = json.loads(line[5:].strip())
                    if ev.get("type") == "done":
                        got_done, status = True, ev.get("status")
                        break
        check("SSE delivered done", got_done)
        check("missing bundle -> error status", status == "error", f"status={status}")
    finally:
        httpd.shutdown()


def main():
    test_imports()
    test_jobs()
    test_http()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} -> {FAILS}")
        raise SystemExit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
