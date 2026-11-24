"""Write tests/fixtures/mv_studio_tracks_12035.json, the 12035 timeline structure.

    python3 tests/fixtures/make_mv_studio_tracks_12035.py <input> tests/fixtures/mv_studio_tracks_12035.json

<input> is either the MV's native Android timeline bundle (12035-android-timeline.unity,
from the game's asset cache; it is not in the repository), which is parsed here with
webtools.core.mv_studio_timeline.parse_timeline, or a JSON file holding that parse result.

Only the timeline structure is kept: kind, nativeClass, binding, label, clip label, start,
duration, the four extrapolation values and the editableValues key names. Track and event
ids are anonymised (t00, t00:0, ...) so no CAB names or path ids are written, and no
playable values are kept. A track-level editableValues is the list most of its events
share; an event that differs lists its own. The output is written one clip per line.
"""
import json
import sys
from pathlib import Path

TIMING = ("preExtrapolationMode", "postExtrapolationMode", "preExtrapolationTime", "postExtrapolationTime")
SOURCE = ("MV 12035 (Android) native timeline parsed with core.mv_studio_timeline.parse_timeline "
          "(written by tests/fixtures/make_mv_studio_tracks_12035.py). "
          "Structure and clip timing only: ids are anonymised, playable values are dropped "
          "(only the extrapolation timing values and editableValues key names are kept). "
          "A track-level editableValues is the list shared by its events unless an event lists its own.")


def parsed(path):
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from webtools.core import mv_studio_timeline
    return mv_studio_timeline.parse_timeline(path.read_bytes(), "12035")


def structure(data):
    tracks = []
    for index, track in enumerate(data["tracks"]):
        track_id = f"t{index:02d}"
        row = {"id": track_id, "kind": track["kind"], "nativeClass": track.get("nativeClass")}
        if track.get("binding"):
            row["binding"] = track["binding"]
        row["label"] = track["label"]
        lists = [event["editableValues"] for event in track["events"]]
        shared = max(lists, key=lists.count) if lists else None
        if shared is not None:
            row["editableValues"] = shared
        events = []
        for clip, event in enumerate(track["events"]):
            item = {"id": f"{track_id}:{clip}", "label": event.get("label", ""), "start": event["start"],
                    "duration": event["duration"], "values": {key: event["values"][key] for key in TIMING if key in event["values"]}}
            if event["editableValues"] != shared:
                item["editableValues"] = event["editableValues"]
            events.append(item)
        row["events"] = events
        tracks.append(row)
    return tracks


def write(target, duration, tracks):
    lines = ["{", f'  "source": {json.dumps(SOURCE)},', f'  "duration": {json.dumps(duration)},', '  "tracks": [']
    for position, track in enumerate(tracks):
        head = {key: value for key, value in track.items() if key != "events"}
        text = "    " + json.dumps(head, ensure_ascii=False)[:-1] + ', "events": ['
        events = track["events"]
        for clip, event in enumerate(events):
            text += "\n      " + json.dumps(event, ensure_ascii=False) + ("," if clip + 1 < len(events) else "")
        text += ("\n    " if events else "") + "]}" + ("," if position + 1 < len(tracks) else "")
        lines.append(text)
    lines += ["  ]", "}", ""]
    Path(target).write_text("\n".join(lines), encoding="utf-8")


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    data = parsed(Path(argv[1]))
    write(argv[2], data["duration"], structure(data))


if __name__ == "__main__":
    main(sys.argv)
