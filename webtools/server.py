"""Standard-library HTTP server for the modding-tools WebUI.

No third-party web framework: a ThreadingHTTPServer + BaseHTTPRequestHandler
with a small hand-rolled router. Long-running tool runs execute on background
threads (JobManager) and stream their log/progress to the browser over SSE.
"""
import json
import mimetypes
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from webtools import filebrowser
from webtools.core import decode
from webtools.jobs import MANAGER
from webtools.tools import registry

WEB_DIR = Path(__file__).resolve().parent / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "webtools/0.1"

    # keep the console quiet-ish; one line per request
    def log_message(self, fmt, *args):  # noqa: A003
        pass

    # ------------------------------------------------------------------ utils
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _query(self):
        return parse_qs(urlsplit(self.path).query)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path == "/" or path == "/index.html":
                return self._serve_file(WEB_DIR / "index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):])
            if path == "/api/tools":
                return self._send_json({"tools": registry.public_tools(),
                                        "roots": filebrowser.allowed_roots()})
            if path == "/api/fs/roots":
                return self._send_json(filebrowser.roots_listing())
            if path == "/api/fs/list":
                return self._api_fs_list()
            if path == "/api/thumb":
                return self._api_thumb()
            if path == "/api/download":
                return self._api_download()
            if path.startswith("/api/jobs/") and path.endswith("/events"):
                job_id = path[len("/api/jobs/"):-len("/events")]
                return self._api_events(job_id)
            return self._send_json({"error": "not found"}, status=404)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": str(exc)}, status=500)

    # ------------------------------------------------------------------- POST
    def do_POST(self):  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/run/"):
                return self._api_run(path[len("/api/run/"):])
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path[len("/api/jobs/"):-len("/cancel")]
                ok = MANAGER.cancel(job_id)
                return self._send_json({"ok": ok})
            return self._send_json({"error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": str(exc)}, status=500)

    # --------------------------------------------------------------- handlers
    def _serve_file(self, fpath: Path, content_type=None):
        if not fpath.is_file():
            return self._send_json({"error": "not found"}, status=404)
        if content_type is None:
            content_type = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
        self._send_bytes(fpath.read_bytes(), content_type)

    def _serve_static(self, rel):
        # jail static serving inside WEB_DIR/static
        rel = posixpath.normpath(unquote(rel)).lstrip("/")
        if rel.startswith(".."):
            return self._send_json({"error": "forbidden"}, status=403)
        return self._serve_file(WEB_DIR / "static" / rel)

    def _api_fs_list(self):
        path = (self._query().get("path") or [""])[0]
        try:
            return self._send_json(filebrowser.list_dir(path))
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)
        except (NotADirectoryError, FileNotFoundError) as exc:
            return self._send_json({"error": str(exc)}, status=404)

    def _api_thumb(self):
        path = (self._query().get("path") or [""])[0]
        if not filebrowser.is_within_allowed(path):
            return self._send_json({"error": "forbidden"}, status=403)
        data = decode.thumbnail(path)
        if not data:
            return self._send_json({"error": "no thumbnail"}, status=404)
        self._send_bytes(data, "image/png",
                         extra_headers={"Cache-Control": "max-age=600"})

    def _api_download(self):
        path = (self._query().get("path") or [""])[0]
        if not filebrowser.is_within_allowed(path):
            return self._send_json({"error": "forbidden"}, status=403)
        real = os.path.realpath(os.path.expanduser(path))
        if not os.path.isfile(real):
            return self._send_json({"error": "not found"}, status=404)
        name = os.path.basename(real)
        with open(real, "rb") as f:
            data = f.read()
        self._send_bytes(data, "application/octet-stream",
                         extra_headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def _validate_run_paths(self, tool, params):
        """Reject any path/dir param that points outside the allowed roots."""
        for field in tool.get("fields", []):
            if field["type"] in ("path", "dir"):
                val = params.get(field["name"])
                if val and not filebrowser.is_within_allowed(val):
                    raise PermissionError(f"{field['name']} is outside the allowed roots")

    def _api_run(self, tool_id):
        tool = registry.get_tool(tool_id)
        if not tool:
            return self._send_json({"error": f"unknown tool: {tool_id}"}, status=404)
        params = self._read_json_body()
        try:
            self._validate_run_paths(tool, params)
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)

        job = MANAGER.create(tool_id)
        run_fn = tool["run"]
        MANAGER.run_async(job, lambda j: run_fn(j, params))
        return self._send_json({"job_id": job.id})

    def _api_events(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._send_json({"error": "unknown job"}, status=404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        index = 0
        try:
            while True:
                event = job.event_at(index, timeout=10.0)
                if event is None:
                    if job.is_done and index >= job.event_count:
                        break
                    # heartbeat comment keeps proxies/WebViews from dropping us
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(event)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                index += 1
                if event.get("type") == "done":
                    break
        except (BrokenPipeError, ConnectionResetError):
            return None


def serve(host: str, port: int):
    mimetypes.add_type("application/javascript", ".js")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
