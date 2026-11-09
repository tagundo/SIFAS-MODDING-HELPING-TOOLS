"""Normal HTTP handler with a private original voice prepared in its process."""
import argparse
import json
from pathlib import Path
from http.server import ThreadingHTTPServer

from webtools.core.game_motion_audio import prepare_audio
from webtools.jobs import Job
from webtools.server import Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--descriptor", required=True)
    args = parser.parse_args()
    data = prepare_audio(Job("private-audio", "viewer-motion"), repo_root=Path(args.repo),
        output_root=Path(args.library) / "audio", record={"region": "gl", "category": "voice", "download": False}, timeline_paths=[args.timeline])
    if not data["tracks"] or data["warnings"]:
        raise RuntimeError("The private original voice did not prepare: " + str(data))
    Path(args.descriptor).write_text(json.dumps(data), encoding="utf-8")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
