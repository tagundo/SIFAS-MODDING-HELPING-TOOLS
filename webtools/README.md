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

Open the **3D model** tab, choose a Unity costume file or costume ZIP from
`models`, `modded` or `suit`, and press **Open model**. Extensionless UnityFS
members in costume ZIPs are supported. ZIP contents are read into a bounded
temporary folder which is removed after conversion.
The viewer keeps the original files unchanged. On Android the editing tabs
prepare their local tools automatically; the game server can remain stopped.

**Automatically add the original face** is on by default. The viewer identifies
the character from the selected Unity data and validated costume metadata,
searches same-character originals in the local library, and can reuse or
download their original facial packs using Elichika's asset database. Only
missing Face/Eyes parts are added; the mod's body and hair stay selected.
Downloads are bounded and cached. If a facial source cannot be obtained, the
costume remains visible with a warning. Disable this option to inspect the
selected files alone. Standalone installations can use local originals; online
lookup also needs Elichika's asset database and bundled asset extractor.
Original LZMA-compressed facial bundles are decoded with bounded memory; manual
repacking is unnecessary and the source files remain unchanged.

- Drag to rotate, pinch/scroll to zoom, or use two fingers to pan.
- **Front**, **Back**, side views and **Fit model** reset the camera.
- **Expand view** gives the model more room on a phone.
- **Pose and body** selects available motion clips, plays/pauses or seeks them,
  and adjusts expression channels. **Add animation file** selects another Unity
  animation bundle. Same-character local eye-animation companions can also be
  discovered within the bounded trusted library search.
- **Height** and **Breast size** adjust the model's verified `Move` and
  `BreastSize` nodes. `100%` adds no extra change to the current pose/baseline.
  **Use saved node settings** explicitly applies supported absolute LiveCore
  scale/position endpoints; conflicting entries are skipped and reported.
  **Individual bones** provides additional relative transform controls.
- **Reset preview adjustments** restores the saved pose and controls. These
  preview changes do not write to the source bundle. The separate LiveCore and
  Mesh Baker tools save persistent edits; Node Scaling Fix also exposes the
  optional raw game `heightScale` setting for single-file runs.
- **Display options** contains perspective, background, wireframe, textures and
  individual part visibility. **SIFAS material preview** reconstructs supported
  AS/Member equations; **Basic textures** retains the simpler texture view.
  Switching tabs pauses drawing and motion without discarding the current pose.

Interactive previews retain named skeletons, bind poses, skin weights and
supported morph/animation data, including edited models with recentered vertices.
Meshes without valid rig data remain viewable with their saved placement;
unsupported controls stay disabled. Loading an arbitrary model does not provide
the game's dedicated suit-preview clip, and no neutral expression is guessed.
The separate game `heightScale` normalization formula is not inferred by the
preview. Saved Euler-rotation records are not currently applied; individual
bone rotation controls remain available.

Supported AS/Member materials use the APK's gamma-space mask, ambient/tint,
rim-light, matcap, cheek, emissive and outline equations with the source material
flags and available textures. Supported authored mip levels are decoded without
generating or resampling pixels. Known member materials ignore the unused generic
`_Color` field. Unknown materials keep their normal texture fallback. This is not
a claim of pixel-identical game rendering: runtime lighting/controller values,
camera, shadows and postprocessing have not all been captured from the game.
Some SIFAS base costumes contain only the face shell; their eyes and expressions
require a separate facial asset. Missing parts or unsupported
textures are reported above the model. Supported raw and ASTC texture images
retain their original dimensions and pixels. Android includes the ASTC decoder;
desktop users can point `ASTCENC_BIN` at an executable `astcenc`/`astcdec` CLI.

Three.js r128 and its matching controls/loader are bundled under `static/vendor`
with their MIT license, so rendering scripts work offline. The local server converts
selected Unity data to a self-contained GLB in a bounded, temporary memory cache.
Generated previews expire; opening a file again rebuilds them. The converter
keeps implicit Unity filesystem dependency loading disabled. Optional original
facial sources are resolved separately within trusted library/cache roots.

The supplied GL client APK and these projects informed camera/material handling:
[SIFAS-Model-Viewer](https://github.com/a2561024/SIFAS-Model-Viewer) and
[SIFAS-Model-Viewer-Server](https://github.com/a2561024/SIFAS-Model-Viewer-Server).
Those projects serve pre-exported FBX/PNG data. Their application code and game
assets are not included in this implementation.
