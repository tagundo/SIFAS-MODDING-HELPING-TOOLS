"""Compare original game MV frames with MV Studio editor frames at the same time.

    python tests/mv_frame_compare.py --capture CAPTURE/capture.json --video game.mp4 --out REPORT
        [--game-info info.json] [--align audio|none|SECONDS] [--search 2]
        [--baseline OLD/report.json] [--fail-on-regression]
    python tests/mv_frame_compare.py --capture CAPTURE/capture.json --game-frame 14.85=shot.png --out REPORT

The game MP4 export is fixed-step: video frame N is the game state at N/fps of its
own clock. Timeline time t maps to video time t + soundtrack offset - audio lag,
where the lag is measured by cross-correlating the MP4's audio with the editor's
decoded soundtrack. Neighbouring video frames are scored too, so an off-by-one
timing error shows up as a better neighbour instead of as a rendering difference.

Images are only resized here to bring the two frames to one comparison size; the
smaller frame is never enlarged. Nothing is written back to game assets.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw

SCHEMA = 1
AUDIO_RATE = 8000
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


# ---------------------------------------------------------------- media input

def _tool(name):
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} is required to read the game video. Install FFmpeg or pass --game-frame images.")
    return path


def _rate(value):
    if not value or value in ("0/0", "0"):
        return None
    numerator, _, denominator = value.partition("/")
    rate = float(numerator) / float(denominator or 1)
    return rate if rate > 0 else None


def probe_video(path):
    output = subprocess.run([_tool("ffprobe"), "-v", "error", "-show_entries",
                             "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,"
                             "start_time,nb_frames,color_space,color_range,color_transfer,color_primaries,pix_fmt",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
    streams = json.loads(output).get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("The game video has no video stream.")
    fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
    if not fps:
        raise ValueError("The game video has no constant frame rate.")
    return {
        "width": int(video["width"]), "height": int(video["height"]), "fps": fps,
        "fpsText": video.get("avg_frame_rate"), "codec": video.get("codec_name"), "pixelFormat": video.get("pix_fmt"),
        "startTime": float(video.get("start_time") or 0), "frames": int(video["nb_frames"]) if video.get("nb_frames", "").isdigit() else None,
        "colorSpace": video.get("color_space"), "colorRange": video.get("color_range"),
        "colorTransfer": video.get("color_transfer"), "colorPrimaries": video.get("color_primaries"),
        "audio": any(stream.get("codec_type") == "audio" for stream in streams),
    }


def _color_filter(probe):
    """Convert YUV with the stream's own matrix; untagged HD video is treated as BT.709."""
    matrix = {"bt709": "bt709", "bt470bg": "bt601", "smpte170m": "bt601", "bt2020nc": "bt2020"}.get(probe.get("colorSpace") or "")
    assumed = matrix is None
    matrix = matrix or ("bt709" if probe["height"] >= 720 else "bt601")
    source_range = "pc" if probe.get("colorRange") == "pc" else "tv"
    return (f"scale=in_color_matrix={matrix}:in_range={source_range}:out_range=pc:flags=accurate_rnd+full_chroma_int",
            {"matrix": matrix, "range": source_range, "assumed": assumed})


def decode_audio(path, seconds=None):
    command = [_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path)]
    if seconds:
        command += ["-t", str(seconds)]
    command += ["-vn", "-ac", "1", "-ar", str(AUDIO_RATE), "-f", "f32le", "-"]
    data = subprocess.run(command, check=True, capture_output=True).stdout
    return np.frombuffer(data, np.float32).copy()


def extract_frames(path, probe, indices):
    """Decode exactly the listed frame indices (by presentation time) as RGB uint8 arrays."""
    if not indices:
        return {}
    fps, start = probe["fps"], probe["startTime"]
    first, last = min(indices), max(indices)
    low, high = start + (first - 0.5) / fps, start + (last + 0.5) / fps
    seek = max(0.0, low - 1.0)
    color, _ = _color_filter(probe)
    command = [_tool("ffmpeg"), "-v", "info", "-hide_banner", "-nostats", "-nostdin", "-copyts", "-ss", f"{seek:.6f}",
               "-i", str(path), "-map", "0:v:0",
               "-vf", f"select='between(t\\,{low:.6f}\\,{high:.6f})',showinfo,{color},format=rgb24",
               "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    result = subprocess.run(command, check=True, capture_output=True)
    times = [float(value) for value in re.findall(rb"Parsed_showinfo.*?pts_time:\s*([-0-9.e]+)", result.stderr)]
    size = probe["width"] * probe["height"] * 3
    if len(result.stdout) != size * len(times):
        raise ValueError("FFmpeg returned an unexpected number of video frames.")
    frames = {}
    for position, pts in enumerate(times):
        index = round((pts - start) * fps)
        if index in indices:
            frame = np.frombuffer(result.stdout, np.uint8, size, position * size)
            frames[index] = frame.reshape(probe["height"], probe["width"], 3).copy()
    return frames


def load_image(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).copy()


# ------------------------------------------------------------ time alignment

def audio_lag(video_audio, soundtrack, max_lag=10.0, window=120.0, expected=None):
    """Return lag d (seconds) where video audio at v matches soundtrack at v + d.

    Looped music can correlate almost as well one bar away. A peak within 0.03 of
    the best is a tie; ties are resolved toward `expected` and reported as ambiguous.
    """
    count = int(window * AUDIO_RATE)
    v = np.asarray(video_audio[:count], np.float64)
    s = np.asarray(soundtrack[:count + int(max_lag * AUDIO_RATE)], np.float64)
    if len(v) < AUDIO_RATE or len(s) < AUDIO_RATE or not v.std() or not s.std():
        return None
    v, s = v - v.mean(), s - s.mean()
    size = 1 << int(math.ceil(math.log2(len(v) + len(s))))
    corr = np.fft.irfft(np.fft.rfft(s, size) * np.conj(np.fft.rfft(v, size)), size)
    limit = int(max_lag * AUDIO_RATE)
    ahead, behind = min(limit, len(s) - 1), min(limit, len(v) - 1)
    lags = np.concatenate([np.arange(0, ahead + 1), np.arange(-behind, 0)])
    values = np.concatenate([corr[:ahead + 1], corr[size - behind:]])
    best = int(np.argmax(values))
    lag = int(lags[best])

    def pearson(shift):
        a, b = (v[:len(s) - shift], s[shift:]) if shift >= 0 else (v[-shift:], s[:len(v) + shift])
        n = min(len(a), len(b))
        if n < AUDIO_RATE:
            return 0.0
        a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
        denominator = math.sqrt(float(a @ a) * float(b @ b))
        return float(a @ b / denominator) if denominator else 0.0

    guard = int(0.05 * AUDIO_RATE)
    candidates, remaining = [], values.copy()
    for _ in range(5):
        index = int(np.argmax(remaining))
        if not np.isfinite(remaining[index]):
            break
        shift = int(lags[index])
        candidates.append({"lag": shift / AUDIO_RATE, "correlation": pearson(shift)})
        remaining[np.abs(lags - shift) <= guard] = -np.inf
    candidates.sort(key=lambda item: -item["correlation"])
    first = candidates[0]
    ties = [item for item in candidates if first["correlation"] - item["correlation"] < 0.03]
    chosen = min(ties, key=lambda item: abs(item["lag"] - expected)) if expected is not None else first
    runner = next((item for item in candidates if item is not chosen), {"lag": None, "correlation": 0.0})
    return {"lag": chosen["lag"], "correlation": chosen["correlation"], "runnerUp": runner["correlation"],
            "runnerUpLag": runner["lag"], "ambiguous": len(ties) > 1, "candidates": candidates,
            "confident": chosen["correlation"] >= 0.8 and (len(ties) == 1 or expected is not None)}


# ------------------------------------------------------------------- metrics

def _resize(array, size):
    if (array.shape[1], array.shape[0]) == size:
        return array
    return np.asarray(Image.fromarray(array).resize(size, Image.Resampling.LANCZOS))


def _gaussian(x, sigma=1.5, radius=5):
    kernel = np.exp(-np.arange(-radius, radius + 1) ** 2 / (2 * sigma * sigma)).astype(np.float32)
    kernel /= kernel.sum()
    padded = np.pad(x, radius, mode="reflect")
    height, width = x.shape
    rows = sum(kernel[i] * padded[:, i:i + width] for i in range(2 * radius + 1))
    return sum(kernel[i] * rows[i:i + height, :] for i in range(2 * radius + 1))


def ssim_map(a, b):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ma, mb = _gaussian(a), _gaussian(b)
    va, vb, cov = _gaussian(a * a) - ma * ma, _gaussian(b * b) - mb * mb, _gaussian(a * b) - ma * mb
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))


def luma(rgb):
    return (rgb.astype(np.float32) / 255.0) @ LUMA


def _edges(y):
    blurred = _gaussian(y, 1.0, 3)
    gy, gx = np.gradient(blurred)
    return np.hypot(gx, gy)


def _ncc(a, b):
    a, b = a - a.mean(), b - b.mean()
    denominator = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / denominator) if denominator else 0.0


def _phase(reference, moving):
    """Shift (dx, dy) to apply to `moving` so it lines up with `reference`, and the peak height."""
    height, width = reference.shape
    window = np.outer(np.hanning(height), np.hanning(width)).astype(np.float32)
    spectrum = np.fft.fft2(reference * window) * np.conj(np.fft.fft2(moving * window))
    spectrum /= np.abs(spectrum) + 1e-9
    surface = np.real(np.fft.ifft2(spectrum))
    y, x = np.unravel_index(int(np.argmax(surface)), surface.shape)

    def refine(values, index, length):
        left, centre, right = values[(index - 1) % length], values[index], values[(index + 1) % length]
        denominator = left - 2 * centre + right
        return index + (0.5 * (left - right) / denominator if denominator else 0.0)

    dy, dx = refine(surface[:, x], y, height), refine(surface[y, :], x, width)
    dy, dx = (dy - height if dy > height / 2 else dy), (dx - width if dx > width / 2 else dx)
    return float(dx), float(dy), float(surface[y, x])


def _scaled(image, scale):
    height, width = image.shape
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = np.asarray(Image.fromarray(image, "F").resize(size, Image.Resampling.BILINEAR))
    result = np.zeros_like(image)
    sy, sx = (size[1] - height) // 2, (size[0] - width) // 2
    src = resized[max(0, sy):max(0, sy) + height, max(0, sx):max(0, sx) + width]
    oy, ox = max(0, -sy), max(0, -sx)
    result[oy:oy + src.shape[0], ox:ox + src.shape[1]] = src
    return result


def geometry(game_y, editor_y, editor_fov=None, limit=480):
    """Estimate the translation and zoom that best maps the editor frame onto the game frame."""
    factor = min(1.0, limit / game_y.shape[0])
    size = (max(16, round(game_y.shape[1] * factor)), max(16, round(game_y.shape[0] * factor)))
    small = lambda y: np.asarray(Image.fromarray(y, "F").resize(size, Image.Resampling.BILINEAR))
    reference, moving = _edges(small(game_y)), _edges(small(editor_y))
    best = None
    for scale in np.round(np.arange(0.90, 1.1001, 0.005), 3):
        dx, dy, peak = _phase(reference, _scaled(moving, float(scale)))
        if best is None or peak > best[3]:
            best = (float(scale), dx, dy, peak)
    scale, dx, dy, peak = best
    result = {"scale": scale, "dx": dx / factor, "dy": dy / factor, "peak": peak,
              "structureNCC": _ncc(reference, moving)}
    if editor_fov and 0 < editor_fov < 180:
        result["impliedGameFov"] = math.degrees(2 * math.atan(math.tan(math.radians(editor_fov) / 2) / scale))
    return result


def _tiles(ssim, columns=8):
    height, width = ssim.shape
    rows = max(1, round(columns * height / width))
    tiles = []
    for row in range(rows):
        for column in range(columns):
            y0, y1 = row * height // rows, (row + 1) * height // rows
            x0, x1 = column * width // columns, (column + 1) * width // columns
            tiles.append({"row": row, "column": column, "box": [x0, y0, x1, y1], "ssim": float(ssim[y0:y1, x0:x1].mean())})
    return tiles


def compare(game_rgb, editor_rgb, editor_fov=None):
    game_aspect, editor_aspect = game_rgb.shape[1] / game_rgb.shape[0], editor_rgb.shape[1] / editor_rgb.shape[0]
    if abs(game_aspect / editor_aspect - 1) > 0.005:
        raise ValueError(f"The frames have different aspect ratios ({game_aspect:.4f} and {editor_aspect:.4f}). "
                         "Capture the editor at the game video's aspect.")
    target = min((game_rgb.shape[1], game_rgb.shape[0]), (editor_rgb.shape[1], editor_rgb.shape[0]), key=lambda size: size[1])
    game, editor = _resize(game_rgb, target), _resize(editor_rgb, target)
    gy, ey = luma(game), luma(editor)
    ssim = ssim_map(gy, ey)
    error = (game.astype(np.float32) - editor.astype(np.float32)) / 255.0
    mse = float((error ** 2).mean())
    tiles = _tiles(ssim)
    return {
        "size": list(target), "game": game, "editor": editor, "ssimMap": ssim, "absLuma": np.abs(gy - ey),
        "metrics": {
            "ssim": float(ssim.mean()), "psnr": float("inf") if mse == 0 else 10 * math.log10(1 / mse),
            "mae": [float(value) for value in np.abs(error).mean(axis=(0, 1))],
            "meanGame": [float(value) for value in game.reshape(-1, 3).mean(axis=0) / 255],
            "meanEditor": [float(value) for value in editor.reshape(-1, 3).mean(axis=0) / 255],
            "lumaMeanDelta": float(ey.mean() - gy.mean()),
            "lumaP95Delta": float(np.percentile(ey, 95) - np.percentile(gy, 95)),
        },
        "geometry": geometry(gy, ey, editor_fov),
        "worstTiles": sorted(tiles, key=lambda tile: tile["ssim"])[:6],
    }


def quick_ssim(game_rgb, editor_rgb, height=270):
    width = round(editor_rgb.shape[1] * height / editor_rgb.shape[0])
    return float(ssim_map(luma(_resize(game_rgb, (width, height))), luma(_resize(editor_rgb, (width, height)))).mean())


# ------------------------------------------------------------------- images

_HEAT = np.array([[0, 0, 4], [59, 15, 112], [140, 41, 129], [222, 73, 104], [254, 159, 109], [252, 253, 191]], np.float32)


def heat(values):
    values = np.clip(values, 0, 1) * (len(_HEAT) - 1)
    low = np.floor(values).astype(int).clip(0, len(_HEAT) - 2)
    fraction = (values - low)[..., None]
    return (_HEAT[low] * (1 - fraction) + _HEAT[low + 1] * fraction).astype(np.uint8)


def composite(result, title, path, width=960):
    tiles = [("Game", result["game"]), ("Editor", result["editor"]),
             ("|luma diff| x4", heat(result["absLuma"] * 4)), ("1 - SSIM", heat(1 - result["ssimMap"]))]
    height = round(width * result["size"][1] / result["size"][0])
    banner = 28
    canvas = Image.new("RGB", (width * 2, (height + banner) * 2 + banner), (16, 16, 20))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 6), title, fill=(235, 235, 235))
    for index, (label, image) in enumerate(tiles):
        x, y = (index % 2) * width, banner + (index // 2) * (height + banner)
        draw.text((x + 8, y + 6), label, fill=(235, 235, 235))
        canvas.paste(Image.fromarray(image).resize((width, height), Image.Resampling.BILINEAR), (x, y + banner))
    for tile in result["worstTiles"][:3]:
        scale = width / result["size"][0]
        x0, y0, x1, y1 = (round(value * scale) for value in tile["box"])
        for offset in (0, width):
            draw.rectangle([x0 + offset, y0 + banner, x1 + offset, y1 + banner], outline=(80, 220, 255), width=2)
    canvas.save(path)


# ------------------------------------------------------------------- report

def _key(time):
    return f"{time:.4f}"


def baseline_deltas(frames, baseline, threshold):
    previous = {_key(frame["time"]): frame for frame in baseline.get("frames", [])}
    deltas = []
    for frame in frames:
        old = previous.get(_key(frame["time"]))
        if not old:
            continue
        delta = {"time": frame["time"],
                 "ssim": frame["metrics"]["ssim"] - old["metrics"]["ssim"],
                 "structureNCC": frame["geometry"]["structureNCC"] - old["geometry"]["structureNCC"]}
        delta["regressed"] = delta["ssim"] < -threshold
        deltas.append(delta)
    return deltas


def _scope(capture, game_info, alignment):
    renderer = ((capture.get("environment") or {}).get("webgl") or {}).get("renderer") or ""
    return {
        "gameFrames": game_info or {"note": "No --game-info was given; record the client build, device, platform and FOV."},
        "editorFrames": {"webglRenderer": renderer, "software": bool(re.search(r"SwiftShader|llvmpipe|Software", renderer, re.I)),
                         "modtools": (capture.get("environment") or {}).get("modtools")},
        "timeAlignment": alignment["method"],
        "limits": "Per-frame image metrics only. Values are comparable between runs with the same game video, "
                  "editor render size and comparison size.",
    }


def run(arguments):
    capture_path = Path(arguments.capture).resolve()
    capture = json.loads(capture_path.read_text("utf-8"))
    if capture.get("kind") != "elichika-mv-editor-frames":
        raise SystemExit("--capture must be a capture.json written by tests/mv_frame_capture.js")
    out = Path(arguments.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    game_info = json.loads(Path(arguments.game_info).read_text("utf-8")) if arguments.game_info else (capture["manifest"].get("game") or None)
    offset = float(((capture.get("project") or {}).get("soundtrack") or {}).get("offset") or 0)
    manual = {}
    for item in arguments.game_frame or []:
        time, _, file = item.partition("=")
        manual[_key(float(time))] = Path(file)
    probe, alignment = None, {"method": "manual-images", "soundtrackOffset": offset}
    if not manual:
        if not arguments.video:
            raise SystemExit("Pass --video with the game MP4 export or --game-frame TIME=PNG.")
        probe = probe_video(arguments.video)
        lag, alignment = offset, {"method": "assumed", "soundtrackOffset": offset}
        if arguments.align == "audio":
            soundtrack = capture.get("soundtrack")
            audio = None
            if probe["audio"] and soundtrack and (capture_path.parent / soundtrack).exists():
                audio = audio_lag(decode_audio(arguments.video, 150), decode_audio(capture_path.parent / soundtrack, 180), expected=offset)
            if audio and audio["confident"]:
                lag = audio["lag"]
                alignment = {"method": "audio", "soundtrackOffset": offset, **audio}
            else:
                alignment = {"method": "assumed", "soundtrackOffset": offset, "audio": audio,
                             "note": "Audio alignment was unavailable or not confident; video time = timeline time."}
        elif arguments.align not in ("none", None):
            lag = offset - float(arguments.align)
            alignment = {"method": "manual-offset", "soundtrackOffset": offset, "videoMinusTimeline": float(arguments.align)}
        alignment["mapping"] = "videoTime = time + soundtrackOffset - lag"
        alignment["lag"] = lag
        _, alignment["color"] = _color_filter(probe)
    frames = []
    for frame in capture["frames"]:
        time = float(frame["time"])
        editor = load_image(capture_path.parent / frame["image"])
        state = frame.get("state") or {}
        fov = (state.get("camera") or {}).get("fov")
        record = {"time": time, "label": frame.get("label"), "editorImage": str(capture_path.parent / frame["image"]),
                  "editorCamera": state.get("camera"), "cameraEvent": state.get("cameraEvent"),
                  "liveShot": state.get("liveShot"), "splitCameras": state.get("splitCameras")}
        if manual:
            if _key(time) not in manual:
                continue
            game = load_image(manual[_key(time)])
            record["gameImage"] = str(manual[_key(time)].resolve())
        else:
            video_time = time + offset - alignment["lag"]
            index = round(video_time * probe["fps"])
            last = probe["frames"] - 1 if probe["frames"] else None
            wanted = [value for value in range(index - arguments.search, index + arguments.search + 1)
                      if value >= 0 and (last is None or value <= last)]
            decoded = extract_frames(arguments.video, probe, set(wanted))
            if index not in decoded:
                record["error"] = f"Video frame {index} is outside the game video."
                frames.append(record)
                continue
            neighbours = [{"offset": value - index, "ssim": quick_ssim(decoded[value], editor)} for value in sorted(decoded)]
            best = max(neighbours, key=lambda item: item["ssim"])
            record.update({"videoTime": video_time, "videoFrame": index, "neighbours": neighbours, "bestOffset": best["offset"],
                           "timingSuspect": best["offset"] != 0 and best["ssim"] - next(n["ssim"] for n in neighbours if n["offset"] == 0) > 0.01})
            game = decoded[index]
            image = out / f"game-{_key(time).replace('.', '_')}.png"
            Image.fromarray(game).save(image)
            record["gameImage"] = str(image)
        result = compare(game, editor, fov)
        name = f"compare-{_key(time).replace('.', '_')}.png"
        composite(result, f"t={time:.4f}s  SSIM {result['metrics']['ssim']:.4f}  scale {result['geometry']['scale']:.3f}  "
                          f"shift {result['geometry']['dx']:+.1f},{result['geometry']['dy']:+.1f}px", out / name)
        record.update({"compareSize": result["size"], "metrics": result["metrics"], "geometry": result["geometry"],
                       "worstTiles": result["worstTiles"], "composite": str(out / name)})
        frames.append(record)
    scored = [frame for frame in frames if "metrics" in frame]
    report = {
        "schema": SCHEMA, "kind": "elichika-mv-frame-comparison", "createdAt": datetime.now(timezone.utc).isoformat(),
        "capture": {"path": str(capture_path), "source": capture["manifest"]["source"], "quality": capture.get("quality"),
                    "render": capture.get("render"), "warnings": (capture.get("project") or {}).get("warnings", [])},
        "game": {"video": str(Path(arguments.video).resolve()) if arguments.video and not manual else None, "probe": probe, "info": game_info},
        "alignment": alignment, "scope": _scope(capture, game_info, alignment), "frames": frames,
        "summary": {"frames": len(scored), "meanSSIM": float(np.mean([f["metrics"]["ssim"] for f in scored])) if scored else None,
                    "minSSIM": min((f["metrics"]["ssim"] for f in scored), default=None),
                    "timingSuspects": [f["time"] for f in scored if f.get("timingSuspect")]},
    }
    if arguments.baseline:
        baseline = json.loads(Path(arguments.baseline).read_text("utf-8"))
        report["baseline"] = {"path": str(Path(arguments.baseline).resolve()),
                              "deltas": baseline_deltas(scored, baseline, arguments.regression_threshold)}
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=True) + "\n", "utf-8")
    print(json.dumps({"report": str(out / "report.json"), **report["summary"], "alignment": alignment["method"]}))
    regressions = [delta for delta in report.get("baseline", {}).get("deltas", []) if delta["regressed"]]
    return 2 if arguments.fail_on_regression and regressions else 0


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--capture", required=True, help="capture.json from tests/mv_frame_capture.js")
    result.add_argument("--video", help="game MP4 export of the same MV")
    result.add_argument("--game-frame", action="append", metavar="TIME=PNG", help="game screenshot for one capture time")
    result.add_argument("--game-info", help="JSON describing the game client, device, platform, FOV and quality")
    result.add_argument("--align", default="audio", help="audio (default), none, or video-minus-timeline seconds")
    result.add_argument("--search", type=int, default=2, help="neighbouring video frames to score on each side")
    result.add_argument("--baseline", help="earlier report.json to diff against")
    result.add_argument("--regression-threshold", type=float, default=0.005)
    result.add_argument("--fail-on-regression", action="store_true")
    result.add_argument("--out", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
