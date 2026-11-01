# webtools — local WebUI for the SIFAS modding tools

A small browser UI that wraps the existing modding scripts, so you can run them
from your phone or PC with clicks instead of text menus. It runs a tiny local
web server on your own device and opens in your browser — nothing is uploaded
anywhere.

## What it does

| Tool | Wraps |
|------|-------|
| Breast Physics (Dyna) | `sifas_breast_tuner.py` swing-bone physics |
| Breast Size (LiveCore) | `sifas_breast_tuner.py` scale editing |
| Skirt Length | `skirt_length_changer.py` |
| Texture Importer | replace Texture2D images from a folder |
| 3D model | inspect costume geometry and textures with touch rotation, zoom and camera presets |
| Texture previews | view one representative texture image per costume file |
| Mesh Baker | bake scale, rotation and movement into model vertices |

Each tool runs in **Single file** or **Batch folder** mode, shows a live log and
progress bar, and can be cancelled mid-run.

## Requirements

- Python 3.8+
- `UnityPy` (the tools install this on first run)
- `numpy` — needed for the **3D model** viewer and mesh editing
- `Pillow` — needed for model textures, **Texture Importer** and thumbnails
  - Termux: `pkg install python-pillow`
  - Desktop: `pip install Pillow`

No web framework is required — the server is built on Python's standard library.

## Run it

From the repo root:

```bash
python -m webtools
```

Then open the printed URL (default `http://127.0.0.1:8770/`). On desktop a
browser opens automatically.

Options:

```
--host 0.0.0.0     expose on your LAN (default 127.0.0.1, loopback only)
--port 8770        change the port
--no-browser       don't auto-open a browser
```

### Termux tip (one-tap launch)

Install **Termux:Widget**, then create `~/.shortcuts/SIFAS WebUI`:

```bash
#!/data/data/com.termux/files/usr/bin/bash
cd ~/SIFAS-MODDING-HELPING-TOOLS && python -m webtools --no-browser
```

The home-screen widget then starts the server with one tap; open the URL in your
browser.

## Where files live

The file browser is limited to your sukusta library and home folder:

- `extracted` — `~/sukusta/extracted` (Termux: `~/storage/downloads/sukusta/extracted`)
- `models` — `extracted/3d_model`, the asset extractor's model output; Mesh Baker
  opens here by default, falling back to `extracted` for older libraries
- `modded` — `~/sukusta/modded`
- override the base with the `SUKUSTA_DIR` environment variable

## Notes

- The WebUI calls the **same** functions the command-line tools use, so output is
  identical to running the scripts directly.
- If a texture thumbnail can't be decoded (some Termux/ARM codec builds), the
  gallery just shows a "no preview" placeholder — it never crashes the server.

## Mesh Baker

1. Choose an input model and an output folder.
2. Choose a body-part button, such as **Waist thickness**, **Upper arm thickness**,
   or **Head size**, then adjust its slider. Only the chosen part's controls are
   shown; percentage badges keep the other edits visible. 100% is the original
   size, and both sides change together. The −5% / +5% buttons and Reset offer
   simple adjustments.
3. Press **Save model** in the bottom bar to save a new model. Press **View saved
   model** in the result panel to inspect that exact output in the 3D viewer.

The tool reads the chosen model to enable supported body parts and resolves the
same parts separately for each file in a batch. Thickness keeps limb length and
neighboring sizes; hands, feet and head use overall size. Clothing attached to
these parts can also change. For a batch folder, choose one example model to
enable the controls. Input choices and edits survive mode and language changes.

**Expert options** contains individual bone rows with X/Y/Z scale, rotation and
movement, thigh body-type presets, mesh filters and filename settings. Raw target
specifications are supported by the API and CLI; the browser does not require or
display their syntax. The preview opens an input or saved file; save new edits
before viewing their result.

## 3D model

Open the **3D model** tab, choose a Unity costume file from `models` or `modded`,
and press **Open model**. Add separate face or hair files when they are available.
The viewer keeps the original files unchanged. On Android the editing tabs
prepare their local tools automatically; the game server can remain stopped.

- Drag to rotate, pinch/scroll to zoom, or use two fingers to pan.
- **Front**, **Back**, side views and **Fit model** reset the camera.
- **Expand view** gives the model more room on a phone.
- **Display options** contains perspective, background, wireframe, textures and
  individual part visibility. Switching tabs preserves the loaded model and
  pauses drawing while it is hidden.

This is a static geometry preview. Game lighting, facial expressions and motion
can differ. Some SIFAS base costumes contain only the face shell; their eyes and
expressions require a separate facial asset. Missing parts or unsupported
textures are reported above the model. Supported raw and ASTC texture images
retain their original dimensions and pixels. Android includes the ASTC decoder;
desktop users can point `ASTCENC_BIN` at an executable `astcenc`/`astcdec` CLI.

Three.js r128 and its matching controls/loader are bundled under `static/vendor`
with their MIT license, so viewing uses no external CDN. The local server converts
selected Unity data to a self-contained GLB in a bounded, temporary memory cache.
Generated previews expire; opening a file again rebuilds them. The converter
does not follow filesystem dependencies outside the explicitly chosen files.

The supplied GL client APK and these projects informed camera/material handling:
[SIFAS-Model-Viewer](https://github.com/a2561024/SIFAS-Model-Viewer) and
[SIFAS-Model-Viewer-Server](https://github.com/a2561024/SIFAS-Model-Viewer-Server).
Those projects serve pre-exported FBX/PNG data. Their application code and game
assets are not included in this implementation.
