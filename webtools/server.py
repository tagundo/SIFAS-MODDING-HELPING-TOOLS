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
from urllib.parse import parse_qs, quote, unquote, urlsplit

from webtools import filebrowser
from webtools import i18n
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

    def _lang(self):
        """Requested UI language (``?lang=``), normalised; falls back to English."""
        raw = (self._query().get("lang") or [""])[0]
        return i18n.normalize(raw) or i18n.DEFAULT_LANGUAGE

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
                return self._send_json({"tools": registry.public_tools(self._lang()),
                                        "roots": filebrowser.allowed_roots()})
            if path == "/api/i18n":
                lang = self._lang()
                return self._send_json({"lang": lang,
                                        "languages": i18n.language_options(),
                                        "strings": i18n.all_strings(lang)})
            if path.startswith("/api/options/"):
                return self._api_options(path[len("/api/options/"):])
            if path == "/api/fs/roots":
                return self._send_json(filebrowser.roots_listing())
            if path == "/api/fs/list":
                return self._api_fs_list()
            if path == "/api/thumb":
                return self._api_thumb()
            if path == "/api/download":
                return self._api_download()
            if path.startswith("/api/viewer/model/"):
                return self._api_viewer_model(path[len("/api/viewer/model/"):])
            if path == "/api/viewer/game/catalog":
                return self._api_viewer_game_catalog()
            if path.startswith("/api/viewer/edit/result/"):
                return self._api_viewer_edit_result(path[len("/api/viewer/edit/result/"):])
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
            if path == "/api/viewer/prepare":
                return self._api_viewer_prepare()
            if path == "/api/viewer/game/import":
                return self._api_viewer_game_import()
            if path == "/api/viewer/edit/export":
                return self._api_viewer_edit_export()
            if path == "/api/viewer/edit/package":
                return self._api_viewer_edit_package()
            if path == "/api/viewer/edit/install":
                return self._api_viewer_edit_install()
            if path == "/api/viewer/edit/restore":
                return self._api_viewer_edit_restore()
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
        # HTTP headers are Latin-1. Keep the original Unicode filename in the
        # RFC 5987 parameter, with an ASCII fallback for older download clients.
        import re
        fallback = re.sub(r"[^A-Za-z0-9._-]", "_", name.encode("ascii", "ignore").decode("ascii"))
        if not fallback or fallback.startswith("."):
            fallback = "download" + fallback
        self._send_bytes(data, "application/octet-stream",
                         extra_headers={"Content-Disposition":
                                        f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(name, safe="")}'})

    def _api_viewer_prepare(self):
        # Keep selected paths and feature flags bounded before loading assets.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send_json({"error": "Invalid request size."}, status=400)
        if length <= 0 or length > 16384:
            return self._send_json({"error": "Model request is too large or empty."}, status=400)
        params = self._read_json_body()
        if not isinstance(params, dict):
            return self._send_json({"error": "Choose at least one model file."}, status=400)
        if set(params) - {"paths", "auto_face", "rigged", "archive_variants"}:
            return self._send_json({"error": "Unsupported model viewer option."}, status=400)
        auto_face = params.get("auto_face", True)
        if not isinstance(auto_face, bool):
            return self._send_json({"error": "Automatic face loading must be on or off."}, status=400)
        rigged = params.get("rigged", False)
        if not isinstance(rigged, bool):
            return self._send_json({"error": "Interactive model loading must be on or off."}, status=400)
        paths = params.get("paths")
        if (not isinstance(paths, list) or not 1 <= len(paths) <= 8
                or any(not isinstance(path, str) or not path.strip() for path in paths)):
            return self._send_json({"error": "Choose between one and eight model files."}, status=400)
        choices = params.get("archive_variants", {})
        indices = {str(index): index for index in range(len(paths))}
        if (not isinstance(choices, dict) or len(choices) > len(paths)
                or any(key not in indices for key in choices)):
            return self._send_json({"error": "Costume variant choices must use selected file numbers."}, status=400)
        if any(not isinstance(value, str) or value not in ("primary", "unmasked")
               for value in choices.values()):
            return self._send_json({"error": "Choose primary or unmasked for the costume variant."}, status=400)
        resolved = []
        input_paths = []
        for path in paths:
            real = os.path.realpath(os.path.expanduser(path))
            if not filebrowser.is_within_allowed(real):
                return self._send_json({"error": "Model file is outside the allowed folders."}, status=403)
            if not os.path.isfile(real):
                return self._send_json({"error": "Model file was not found."}, status=404)
            if real not in resolved:
                resolved.append(real)
            input_paths.append(real)
        variant_choices = {}
        for index, choice in choices.items():
            original = input_paths[indices[index]]
            if original in variant_choices and variant_choices[original] != choice:
                return self._send_json({"error": "Conflicting costume variant choices refer to the same file."}, status=400)
            variant_choices[original] = choice
        from webtools.core import model_viewer, viewer_archive
        from webtools.core.sukusta import default_sukusta_dir
        # The UI may select inputs and enable the feature; filesystem and CDN
        # context always come from this application, never from request JSON.
        cache_dir = os.path.join(os.path.realpath(default_sukusta_dir("")), ".viewer-cache")
        context = {
            "enabled": auto_face,
            "allow_download": auto_face,
            "repo_root": str(Path.cwd()),
            "library_roots": list(dict.fromkeys(
                os.path.realpath(root) for root in filebrowser.allowed_roots().values())),
            "cache_dir": cache_dir,
        }
        try:
            with viewer_archive.expand_inputs(resolved, cache_dir, variant_choices=variant_choices) as expanded:
                context.update(manifest_paths=expanded.manifest_paths, origins=expanded.origins)
                options = {"face_context": context}
                if rigged:
                    options["rigged"] = True
                result = model_viewer.prepare(expanded.paths, **options)
                result["source_names"] = expanded.source_names
                # Indices select among the caller's already jailed inputs, never
                # arbitrary archive members or temporary extracted paths.
                result["variants"] = [
                    {"source_index": input_paths.index(item["source_path"]),
                     "source_name": item["source_name"], "selected": item["selected"],
                     "choices": item["choices"]}
                    for item in expanded.variants]
                # The editable inputs must be captured while ZIP members still
                # exist. Auto-discovered faces and motions are deliberately not
                # writable sources, even though they appear in the preview.
                if rigged and result.get("rig", {}).get("available"):
                    from webtools.core import model_edits
                    try:
                        result["editing"] = model_edits.register_session(
                            result["id"], expanded.paths, result["rig"],
                            originals=resolved, origins=expanded.origins,
                            archive_members=getattr(expanded, "archive_members", {}),
                            variants={item["source_path"]: item["selected"]
                                      for item in expanded.variants},
                            cache_dir=cache_dir)
                        if result["editing"].get("available"):
                            from webtools.core import viewer_mod_flow
                            result["editing"]["modPackaging"] = viewer_mod_flow.metadata(
                                model_edits.mod_source_context(result["editing"]["token"]),
                                repo_root=Path.cwd(),
                                cache_root=Path(default_sukusta_dir("extracted")) / "game-models",
                                language=self._lang())
                    except (ValueError, OSError) as exc:
                        # A bounded editing-cache failure must not prevent
                        # opening an otherwise valid read-only model.
                        result["editing"] = {"available": False, "reason": str(exc)}
            return self._send_json(result)
        except (ValueError, TypeError) as exc:
            return self._send_json({"error": str(exc)}, status=400)
        except FileNotFoundError:
            return self._send_json({"error": "Model file was not found."}, status=404)
        except TimeoutError:
            return self._send_json({"error": "Model preparation timed out. Try fewer files."}, status=503)

    def _api_viewer_model(self, name):
        import re
        match = re.fullmatch(r"([a-f0-9]{32})\.glb", name)
        if not match:
            return self._send_json({"error": "Model preview was not found."}, status=404)
        from webtools.core import model_viewer
        data = model_viewer.get_model(match.group(1))
        if data is None:
            return self._send_json({"error": "Model preview expired. Load the model again."}, status=404)
        return self._send_bytes(data, "model/gltf-binary",
                                extra_headers={"Cache-Control": "no-store"})

    def _api_viewer_game_catalog(self):
        from webtools.core import game_models
        from sqlite3 import Error as SQLiteError
        try:
            query = self._query()
            if len(urlsplit(self.path).query) > 2048 or set(query) - {"region", "character", "search", "lang"} or any(len(values) != 1 for values in query.values()):
                raise ValueError("Unsupported game asset search.")
            result = game_models.catalog(Path.cwd(), language=self._lang(),
                region=(query.get("region") or [""])[0],
                character=(query.get("character") or [""])[0],
                search=(query.get("search") or [""])[0])
            return self._send_json(result)
        except (ValueError, OSError) as exc:
            return self._send_json({"error": str(exc)}, status=400)
        except SQLiteError:
            return self._send_json({"error": "Game assets are unavailable. Start or prepare the server data first."}, status=400)

    def _api_viewer_game_import(self):
        from webtools.core import game_models
        from webtools.core.sukusta import default_sukusta_dir
        from sqlite3 import Error as SQLiteError
        try:
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1 or self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise PermissionError("Open the editor from this app before loading game assets.")
            if origins:
                origin = urlsplit(origins[0])
                if (origin.scheme not in ("http", "https") or origin.username or origin.password
                        or origin.path not in ("", "/") or origin.query or origin.fragment
                        or origin.netloc.lower() != (self.headers.get("Host") or "").lower()):
                    raise PermissionError("Open the editor from this app before loading game assets.")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ValueError("Invalid game asset request size.") from None
            if self.headers.get("Transfer-Encoding") or not 0 < length <= 4096:
                raise ValueError("The game asset request is too large or empty.")
            record = game_models.validate_selection(Path.cwd(), self._read_json_body(), self._lang())
            output_root = Path(default_sukusta_dir("extracted")).resolve() / "game-models"
            if output_root.is_symlink() or not filebrowser.is_within_allowed(output_root):
                raise PermissionError("The game model cache is outside the allowed folders.")
            job = MANAGER.create("viewer_game_assets")
            MANAGER.run_async(job, lambda active: game_models.run_import(active,
                repo_root=Path.cwd(), output_root=output_root, record=record))
            return self._send_json({"job_id": job.id})
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)
        except (ValueError, OSError) as exc:
            return self._send_json({"error": str(exc)}, status=400)
        except SQLiteError:
            return self._send_json({"error": "Game assets are unavailable. Start or prepare the server data first."}, status=400)

    def _viewer_edit_request(self, fields):
        """Bound writes to source-bound sessions, without caller output paths."""
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme not in ("http", "https") or parsed.username
                    or parsed.password or parsed.path not in ("", "/")
                    or parsed.query or parsed.fragment
                    or parsed.netloc.lower() != (self.headers.get("Host") or "").lower()):
                raise PermissionError("Open the editor from this app before saving changes.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Invalid editing request size.") from None
        if not 0 < length <= 512 * 1024:
            raise ValueError("The editing request is too large or empty.")
        params = self._read_json_body()
        if not isinstance(params, dict) or set(params) != set(fields):
            raise ValueError("Unsupported editing request.")
        import re
        if not isinstance(params.get("token"), str) or not re.fullmatch(r"[a-f0-9]{32}", params["token"]):
            raise ValueError("Load the original model before editing it.")
        return params

    def _api_viewer_edit_export(self):
        try:
            params = self._viewer_edit_request({"token", "state"})
            if not isinstance(params["state"], dict):
                raise ValueError("Invalid model editing values.")
            from webtools.core import model_edits
            from webtools.core.sukusta import default_sukusta_dir
            # Validate before creating a background job so expired sessions and
            # invalid input remain actionable errors beside the save control.
            validator = getattr(model_edits, "validate_state", None)
            if validator is not None:
                validator(params["token"], params["state"])
            output_dir = os.path.realpath(default_sukusta_dir("modded/viewer"))
            if not filebrowser.is_within_allowed(output_dir):
                raise PermissionError("The model output folder is outside the allowed folders.")
            job = MANAGER.create("viewer_body_edit")

            def save(current):
                if current.should_stop():
                    return "Model saving was cancelled."
                current.progress(0, 1)
                result = model_edits.export(
                    params["token"], params["state"], output_dir, log=current.log)
                # Re-editing opens these immutable original copies, so retain
                # their verified game selection without relying on filenames.
                from webtools.core import viewer_mod_flow
                source_cache = Path(default_sukusta_dir("extracted")).resolve() / "game-models"
                if filebrowser.is_within_allowed(source_cache):
                    try:
                        viewer_mod_flow.remember_export_sources(model_edits.mod_source_context(params["token"]), result,
                            repo_root=Path(getattr(MANAGER, "_runtime_root", Path.cwd())).resolve(), cache_root=source_cache)
                    except (OSError, ValueError, TypeError):
                        current.log("The model was saved, but its automatic game-pairing receipt could not be retained.")
                # Only fully written copies are exposed. The source files are
                # never replaced, and each export owns a distinct directory.
                current._viewer_edit_result = result
                for path in result.get("output_paths", []):
                    current.add_output(path)
                recipe_path = result.get("recipe_path")
                if recipe_path:
                    current.add_output(recipe_path)
                current.progress(1, 1)
                return "Edited model and editing recipe saved."

            MANAGER.run_async(job, save)
            return self._send_json({"job_id": job.id})
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json({"error": str(exc)}, status=400)
        except FileNotFoundError:
            return self._send_json({"error": "The original model is no longer available. Load it again."}, status=404)
        except TimeoutError:
            return self._send_json({"error": "Another model is saving. Try again shortly."}, status=503)

    def _viewer_mod_request(self, fields):
        """Validate app-origin writes; Mod installation accepts an opaque token."""
        import ipaddress
        import re
        try:
            if len(self.headers.get_all("Host", [])) != 1:
                raise ValueError()
            host = urlsplit("//" + (self.headers.get("Host") or ""))
            address, port = self.server.server_address[:2]
            bound = ipaddress.ip_address(address)
            hostname = host.hostname or ""
            if host.username or host.password or host.path or host.query or host.fragment or (host.port or 80) != port:
                raise ValueError()
            if hostname.lower() == "localhost":
                allowed_host = bound.is_loopback or bound.is_unspecified
            else:
                literal = ipaddress.ip_address(hostname)
                allowed_host = bound.is_unspecified or literal == bound or bound.is_loopback and literal.is_loopback
            if not allowed_host:
                raise ValueError()
        except ValueError:
            raise PermissionError("Open the editor at its local app address before creating or adding a Mod ZIP.") from None
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("Open the editor from this app before creating or adding a Mod ZIP.")
        if origins:
            origin = urlsplit(origins[0])
            if (origin.scheme not in ("http", "https") or origin.username or origin.password
                    or origin.path not in ("", "/") or origin.query or origin.fragment
                    or origin.netloc.lower() != (self.headers.get("Host") or "").lower()):
                raise PermissionError("Open the editor from this app before creating or adding a Mod ZIP.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Invalid Mod ZIP request size.") from None
        if self.headers.get("Transfer-Encoding") or not 0 < length <= 512 * 1024:
            raise ValueError("The Mod ZIP request is too large or empty.")
        params = self._read_json_body()
        if not isinstance(params, dict) or set(params) != set(fields):
            raise ValueError("Unsupported Mod ZIP request.")
        key = "token" if "token" in fields else "package_token"
        if not isinstance(params.get(key), str) or not re.fullmatch(r"[a-f0-9]{32}", params[key]):
            raise ValueError("Open the original model or create a fresh Mod ZIP first.")
        return params

    def _api_viewer_edit_package(self):
        try:
            from webtools.core import model_edits, viewer_mod_flow
            from webtools.core.sukusta import default_sukusta_dir
            params = self._viewer_mod_request({"token", "state", "display_name", "character_id", "counterpart_path", "selected_variant"})
            viewer_mod_flow.validate_options(params["display_name"], params["character_id"], params["counterpart_path"], params["selected_variant"])
            model_edits.validate_state(params["token"], params["state"])
            counterpart = params["counterpart_path"]
            if counterpart:
                if len(counterpart) > 4096:
                    raise ValueError("Choose a valid Rina counterpart file.")
                counterpart = os.path.realpath(counterpart)
                if not filebrowser.is_within_allowed(counterpart) or not os.path.isfile(counterpart):
                    raise PermissionError("The Rina counterpart is outside the allowed model folders.")
            output_root = Path(default_sukusta_dir("modded/viewer")).resolve()
            cache_root = Path(default_sukusta_dir("extracted")).resolve() / "game-models"
            if not filebrowser.is_within_allowed(output_root) or not filebrowser.is_within_allowed(cache_root):
                raise PermissionError("The Mod ZIP output folder is outside the allowed folders.")
            runtime_root = Path(getattr(MANAGER, "_runtime_root", Path.cwd())).resolve()
            job = MANAGER.create("viewer_body_mod")

            def package(current):
                current.progress(0, 3)
                result = viewer_mod_flow.create_package(params["token"], params["state"],
                    output_root=output_root, repo_root=runtime_root, cache_root=cache_root,
                    display_name=params["display_name"], character_id=params["character_id"],
                    counterpart_path=counterpart, selected_variant=params["selected_variant"], job=current)
                current._viewer_edit_result = result
                for path in result["output_paths"]:
                    current.add_output(path)
                current.progress(3, 3)
                return "Mod ZIP and editing recipe saved."

            MANAGER.run_async(job, package)
            return self._send_json({"job_id": job.id})
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return self._send_json({"error": str(exc)}, status=400)

    def _api_viewer_edit_install(self):
        try:
            from webtools.core import viewer_mod_flow
            from webtools.core.sukusta import default_sukusta_dir
            params = self._viewer_mod_request({"package_token"})
            viewer_mod_flow.validate_install(params["package_token"])
            runtime_root = Path(getattr(MANAGER, "_runtime_root", Path.cwd())).resolve()
            library_root = Path(default_sukusta_dir("")).resolve()
            if not filebrowser.is_within_allowed(library_root):
                raise PermissionError("The costume library is outside the allowed folders.")
            job = MANAGER.create("viewer_mod_install")

            def install(current):
                result = viewer_mod_flow.install_package(params["package_token"],
                    repo_root=runtime_root, library_root=library_root, job=current)
                current._viewer_edit_result = result
                current.add_output(result["mod_package"]["package_path"])
                return result["summary"]

            from adminui.jobs import JobManager as GuardedJobManager
            if isinstance(MANAGER, GuardedJobManager):
                MANAGER.run_async(job, install)
            else:
                # The standalone editor normally has a lighter job manager.
                # Give this database mutation the same lifecycle/lease order
                # as the native apps, including deferred restart after unlock.
                def guarded_install(current):
                    from adminui.serverctl import whole_job_server
                    from database_maintenance import guard
                    with whole_job_server(current.log) as lifecycle:
                        with guard(runtime_root):
                            summary = install(current)
                            lifecycle.successful = not current.should_stop()
                    return summary
                MANAGER.run_async(job, guarded_install)
            return self._send_json({"job_id": job.id})
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return self._send_json({"error": str(exc)}, status=400)

    def _api_viewer_edit_restore(self):
        try:
            params = self._viewer_edit_request({"token", "recipe"})
            if not isinstance(params["recipe"], dict):
                raise ValueError("Choose an editing recipe for this original model.")
            from webtools.core import model_edits
            state = model_edits.restore(params["token"], params["recipe"])
            return self._send_json({"state": state})
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, status=403)
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json({"error": str(exc)}, status=400)
        except FileNotFoundError:
            return self._send_json({"error": "The original model is no longer available. Load it again."}, status=404)

    def _api_viewer_edit_result(self, job_id):
        import re
        if not re.fullmatch(r"[a-f0-9]{12}", job_id):
            return self._send_json({"error": "The saved model was not found."}, status=404)
        job = MANAGER.get(job_id)
        if job is None or job.tool_id not in ("viewer_body_edit", "viewer_body_mod", "viewer_mod_install"):
            return self._send_json({"error": "The saved model was not found."}, status=404)
        if not job.is_done:
            return self._send_json({"status": job.status}, status=202)
        result = getattr(job, "_viewer_edit_result", None)
        if job.status != "done" or not isinstance(result, dict):
            return self._send_json({"error": "The model was not saved. Check the save status and try again."}, status=400)
        return self._send_json(result)

    def _api_options(self, spec):
        """Serve a dynamic_select field's options: /api/options/<tool>/<field>.
        The field's `options_fn` is called with the query params (its `depends`
        field values, e.g. the donor path). Path dependencies are jailed to the
        allowed roots, exactly like a run."""
        tool_id, _, field_name = spec.partition("/")
        tool = registry.get_tool(tool_id)
        if not tool:
            return self._send_json({"error": "unknown tool", "options": []}, status=404)
        field = next((f for f in tool.get("fields", []) if f.get("name") == field_name), None)
        fn = field.get("options_fn") if field else None
        if not callable(fn):
            return self._send_json({"error": "no options for field", "options": []}, status=404)
        q = {k: v[0] for k, v in self._query().items()}
        by_name = {f.get("name"): f for f in tool.get("fields", [])}
        for dep in field.get("depends", []):
            val = q.get(dep)
            depf = by_name.get(dep)
            if val and depf and depf.get("type") in ("path", "dir") \
                    and not filebrowser.is_within_allowed(val):
                return self._send_json({"error": f"{dep} is outside the allowed roots",
                                        "options": []}, status=403)
        try:
            return self._send_json({"options": fn(q) or []})
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"error": str(exc), "options": []})

    def _validate_run_paths(self, tool, params):
        """Reject any path/dir param that points outside the allowed roots."""
        for field in tool.get("fields", []):
            if field["type"] in ("path", "dir"):
                val = params.get(field["name"])
                if val and not filebrowser.is_within_allowed(val):
                    raise PermissionError(f"{field['name']} is outside the allowed roots")
            elif field["type"] == "paths":
                for p in str(params.get(field["name"]) or "").split("\n"):
                    p = p.strip()
                    if p and not filebrowser.is_within_allowed(p):
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
        if params.get("mode") == "multi":
            from webtools.tools.common import run_multi
            MANAGER.run_async(job, lambda j: run_multi(run_fn, j, params))
        else:
            MANAGER.run_async(job, lambda j: run_fn(j, params))
        return self._send_json({"job_id": job.id})

    def _api_events(self, job_id):
        job = MANAGER.get(job_id)
        if not job:
            return self._send_json({"error": "unknown job"}, status=404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")  # disable any proxy buffering
        self.send_header("Connection", "close")
        self.end_headers()
        # Some Android WebViews buffer a streamed response until a few KB have
        # arrived, which makes every log line appear at once only when the job
        # finishes. A padding comment flushed up front primes the pipe so events
        # are delivered live from the first one.
        self.wfile.write(b":" + b" " * 2048 + b"\n\n")
        self.wfile.flush()

        index = 0
        try:
            while True:
                event = job.event_at(index, timeout=2.0)
                if event is None:
                    if job.is_done and index >= job.event_count:
                        break
                    # heartbeat comment keeps proxies/WebViews from dropping us
                    # (and keeps their buffer flushing) — kept short for liveness
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
