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

- Python 3.11+ (already bundled in the Elichika apps)
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

In an Elichika installation, **Load from game assets** opens a character and
costume picker using the same game catalogs as **Server content → Asset
extraction/decryption**. It reuses downloaded packs and metapacks, optionally
downloads missing data, and opens a separate extracted copy directly in the
viewer. Colour costumes follow their exact game attachment; Rina's unmasked
variant is offered when the selected costume provides one.

**Body and outfit** has a Node Scaling **Hip size** (`HipsSize`, not the parent
`Hips`) card and Mesh Baker **Thigh thickness** and **Waist thickness** cards.
100% restores the loaded shape. Thickness changes the local Y/Z cross-section
and keeps the bone's original local X length; it does not add a height control.
The thigh cards compensate their child bones, and the waist card compensates
at `Spine2`, preserving the upper chest, shoulders and head. The shorter
**Detail body parts** list excludes these dedicated controls; individual fingers,
toes and other bones remain searchable under **All bones** in advanced editing.

Child compensation can also be useful for Node Scaling, but the current Node
exporter does not write it. Uniform or suitably aligned scaling can be expressed
with compensating child position/scale endpoints; rotated nonuniform transforms
can require shear, and game motion may overwrite either endpoint. Use the
supported Mesh Baker compensation when descendants must retain their shape.
The size, breast and skirt Node controls keep their ordinary inheritance.

**Automatically add the original face** is on by default. The viewer identifies
the character from the selected Unity data and validated costume metadata,
searches same-character originals in the local library, and can reuse or
download their original facial packs using Elichika's asset database. Only
missing Face/Eyes parts are added; the mod's body and hair stay selected.
Downloads are bounded and cached. If a facial source cannot be obtained, the
costume remains visible with a warning. Disable this option to inspect the
selected files alone. Standalone installations can use local originals; online
lookup also needs Elichika's asset database and bundled asset extractor.
This lookup uses the costume's character, across the installed GL/JP and
Android/iOS catalogs; it is not limited to one member. Users do not need to
select or upload facial files. Existing game downloads are reused before CDN
downloads, and subsequent previews reuse the private cache.
Original LZMA-compressed facial bundles are decoded with bounded memory; manual
repacking is unnecessary and the source files remain unchanged.

- Drag to rotate, pinch/scroll to zoom, or use two fingers to pan.
- **Front**, **Back**, side views and **Fit model** reset the camera.
- Pose, quality and camera controls sit along the viewport edges. The centre
  remains available for rotating, zooming and moving the model.
- The regular tablet layout keeps the model beside a bounded editing panel;
  taller viewports give a standing character more visible space. **Expand view**
  fills the page with the viewport. **Full screen** also hides the Android app
  chrome and system bars, or uses browser fullscreen when available. Exit with
  the viewport control, Escape or Android Back. Changing view size preserves
  the current pose, edits and camera.
- In the single-column layout, the model scrolls with the page so the editor
  can use the screen below the header. Scrolling does not resize the model or
  change the camera. Wider layouts keep the independent model column visible.
- **Breast size**, **Skirt scale** and **Common adjustments** can be collapsed
  independently. Collapsing a section keeps its selected profile, selected bone,
  saved-setting choices and edited values.
- **Node Scaling** and **Mesh Baker** share the same viewport but have separate
  editing sections. The node section contains breast/skirt controls and its
  recommended bones; the mesh section starts with bones whose scale is animated
  in the audited MV clips. Switching sections changes the available controls,
  not existing edits. Advanced selection can show all bones and choose either
  storage method explicitly. These recommendations cover observed clips, not
  every song or every original-game animation.
- **Thigh thickness** also offers the existing tool's six explicit
  **slim / standard / thick** source-to-target conversions. Choose the original
  and target body types; the app does not guess the costume's source type.
  These profiles retain their exact, unequal width/depth factors and preserve
  bone length with child compensation. Profiles and the uniform percentage are
  alternative adjustments of the same axes: the last applied choice replaces
  the other, always from the loaded original shape. Repeated Apply does not
  compound changes. Choosing no conversion leaves existing edits intact;
  **Undo this size adjustment** explicitly resets those axes.
- **Basic pose** shows the model's authored pose; **Posed view** switches to the
  verified original suit-preview pose. Both buttons pause at the first frame
  and preserve body adjustments, saved-setting choices and individual edits.
  The verified common suit-preview motion is included with the app and works
  offline without selecting a motion file. Posed view stays disabled for
  incompatible skeletons rather than applying partially bound tracks.
- **Pose and motion**, **Body and outfit**, and **Facial expression** are separate
  collapsible panels. Closing one preserves its values and leaves the other
  panels usable. **Pose and motion** selects available clips, plays/pauses or
  seeks them. **Add custom motion** selects another Unity
  animation bundle. Same-character local eye-animation companions can also be
  discovered within the bounded trusted library search.
- The verified **SIFAS costume preview** starts at its first frame, paused; press
  Play for the original motion. **Saved pose** selects the model's authored
  placement. The shared preview motion does not change the costume's character.
- **Breast size** selects the breast tool's exact reference profiles, including
  its irregular smaller profiles. Each choice sets all three local scale axes;
  it does not interpolate a percentage or infer a physical cup size. **No extra
  edits** uses the authored shape plus whichever saved corrections are enabled.
  Undo clears this section's scale edits while respecting the saved-setting
  toggles. Choosing a profile clears earlier manual scale edits to `BreastSize`,
  while keeping its placement and rotation. Custom XYZ editing remains available
  under **Individual bones**.
- Node Scaling's breast, hip and skirt cards initially collapse when every
  controlled current XYZ scale is exactly `1 / 1 / 1`. Non-unit or unavailable
  values stay open. Your fold choices remain during editing; opening another
  model or restoring a recipe sets these initial folds from its actual values.
- **Minimize model**, beside the expanded/full-screen controls, gives the
  editing panel more room without unloading the model. Tall windows keep a
  horizontal **Show model** bar; wide windows keep a narrow restore rail.
  Animation drawing pauses at its current time while hidden. Restoring keeps
  the camera, body values, selection and playback choice, without fitting the
  model again. Body editing and saving remain available while minimized.
- **Height** shows the file's original settings for reference. A natural stature
  formula has not been verified, so there is no extra height slider or vertical
  stretching. The original model and head corrections remain intact. `Move` is
  labelled **Whole model** in advanced editing, rather than presented as a human
  height parameter.
- **Skirt scale** shows the actual local factor stored in the file and the
  current editing value. A file with `0.85` corrections starts at `0.85`.
  **Apply** assigns the entered absolute XYZ factor to each identified skirt
  root, matching the skirt tool; it does not multiply the existing corrections.
  Different per-bone or per-axis values remain distinct in the expanded table.
  Undo clears skirt scale edits, including manual root-scale overrides, without
  changing saved-setting toggles or manual position/rotation edits.
- **File values** are immutable stored NodeScaling endpoints, or explicitly
  labelled authored fallbacks when no saved entry exists. Switching a correction
  off changes **Current editing values**, not the file readout. Conflicting and
  unsupported records are labelled rather than replaced by an apparent file value.
- Saved body and outfit settings are applied by default:
  supported LiveCore scale, position and rotation records cover every exported
  target, including skirt bones. Part groups let you include or exclude settings
  without editing raw bone data; the global checkbox shows the authored shape.
  Saved values are absolute local endpoints, so repeated pose changes do not
  multiply them again. Conflicting or unsupported entries are reported.
  **Individual bones** uses absolute local factors, positions and Unity Euler
  angles. Only explicitly edited axes are pinned; untouched axes inherit the
  active settings and pose. Entering an axis value pins it even when it equals
  the file value. Reset clears those pins. Static editing fields do not animate;
  separate read-only rows show the current pose when it differs. Local X/Y/Z
  do not necessarily correspond to model width, height and depth.
- **Child inverse compensation** is an optional, per-bone switch in advanced
  editing. It cancels the extra inherited scale at the selected descendant
  frames, following Mesh Baker's full-frame compensation; it does not undo
  imported NodeScaling or cancel the parent's translation and rotation. The
  active baseline supplies the ratio for absolute scale edits. Targets can be
  immediate children or the available spine boundaries, with the actual target
  list and any unavailable reason shown beside the control. Child edits remain
  independent. Disabling the switch restores ordinary hierarchy propagation
  without deleting manual values. Undoing the selected bone, or resetting the
  preview, clears the corresponding compensation settings. Automatic affine
  corrections are reported separately from the file and manual TRS values.
- **Reset preview adjustments** restores the verified suit-preview first frame
  when compatible, or otherwise the saved pose, and resets the controls and saved
  settings and part visibility to their loaded defaults. These
  preview changes do not write to the source bundle until **Save edited copy**
  is used. The separate tool forms remain available; Node Scaling Fix also
  exposes the optional raw game `heightScale` setting for single-file runs.
- **Save edited copy** writes the selected body changes to new Unity files or
  updates the relevant model members of a costume ZIP. Other ZIP members and
  installer manifests are retained. Original copies and a
  content-bound `recipe.json` are saved beside the models under
  `sukusta/modded/viewer/body-edit-…/`. Reopening preserved originals and importing
  the recipe rebuilds from those originals rather than repeatedly baking a
  previous result. Camera, animation playhead, expression preview and part
  visibility are viewing choices and are not silently written as body edits.
  If one mod ZIP already contains Android and iOS bundles, **Save edited copy**
  and **Save mod ZIP** apply the same body edits to both platform versions.
  A single bundle keeps its input platform. This also applies on Mac: saving
  does not convert Android bundles to iOS or iOS bundles to Android.
- **Save mod ZIP** creates a package for the costume mod installer. **Add to
  game** packages the current valid edits and installs that package in one
  action; it does not reuse an older download after you change the model or
  its body values. Once installation starts, its progress stays attached to
  that saved package until completion; changing the preview does not retarget
  the installation. After success, **Add to game** stays disabled for the same
  edits and mod name; editing them enables a new copy. **Save edited copy** and
  the native Save shortcut
  still create editable model copies and a recipe.
  The **Mod ZIP** download appears first; the edited preview copy and recipe
  keep separate labels. Use the Mod ZIP for the installer.
  **Mod name** starts with the costume name and the actual edited parts,
  relative factors or selected thigh conversion. You can change it; **Automatic
  name** restores the suggestion. The ZIP, installer manifest and game costume
  share that name. The optional target settings let you identify an otherwise
  unknown character or supply the other Rina model and the edited variant.
  Rina mod packages apply the same source-relative body changes to both board
  and unmasked models, including when you edit only one variant. Each variant
  uses its own original transforms and validated editing session. Missing or mismatched counterpart data prevents
  packaging instead of producing an incomplete installable costume.
- **Open saved result** inspects the actual serialized output. Persistent body
  controls stay locked while inspecting it; pose, motion, camera and expressions
  remain available. **Re-edit from original** restores the saved editing recipe
  on its preserved original files. Save newer body changes before inspecting an
  older result so returning to its recipe cannot discard unsaved edits.
- **Animation priority** shows the loaded clip's own track values after node
  adjustments, including constant scale tracks. It helps expose competing keys;
  it is not a complete SIFAS renderer or a guarantee about unselected MV clips.
  Mesh baking preserves the requested reference-frame shape, but a rotated,
  multiply weighted skin can differ from the live node-edit preview. Inspect
  the saved result when checking its animation. Unsafe rigid-face or read-only
  attachment changes are refused rather than exporting only part of a model.
  Baking currently requires Float32 positions and any normal/tangent channels
  it rewrites; packed geometry can still use saved-node edits when available.
- Expression controls show immutable file and current morph weights. A stored
  negative or over-100% weight is preserved and represented by the raw controls;
  weights are absolute blend weights, not extra bone multipliers. Motion choices
  identify partially supported bindings, and part visibility follows the pose
  until an explicit user visibility choice overrides it.
- **Display options** contains perspective, background, wireframe, textures and
  individual part visibility. **SIFAS material preview** reconstructs supported
  AS/Member equations; **Basic textures** retains the simpler texture view.
  Switching tabs pauses drawing and motion without discarding the current pose.
- **High-quality 3D** uses the device's native display density and requests the
  game's two-sample edge smoothing, retaining stronger existing antialiasing
  where available. It changes rendering only; original mesh and texture pixels
  remain unchanged. The default keeps the existing display-density limit.
  Unsupported devices use their available antialiasing at native density;
  graphics hardware limits still apply. Changing quality preserves the camera,
  pose, motion playback and body/outfit adjustments.

Interactive previews retain named skeletons, bind poses, skin weights and
supported morph/animation data, including edited models with recentered vertices.
Meshes without valid rig data remain viewable with their saved placement;
unsupported controls stay disabled. The bundled 8,826-byte suit-preview clip is
verified by its content hash and exact asset identity, and every track must bind
uniquely before it can become the default pose. A clip name alone cannot select
the default pose, and no neutral expression is guessed.
The separate game `heightScale` normalization formula is not inferred by the
preview. Saved Euler rotations use Unity's Z-X-Y rotation order and the exported
coordinate reflection. The reference evaluator interpolates the original Euler
vectors before conversion, matching the verified native operation; the viewer
applies the file's endpoint values. Individual bone controls remain available.

Supported AS/Member materials use the APK's gamma-space mask, ambient/tint,
rim-light, matcap, cheek, emissive and outline equations with the source material
flags and available textures. Supported authored mip levels are decoded without
generating or resampling pixels. Known member materials ignore the unused generic
`_Color` field. Unknown materials keep their normal texture fallback. This is not
a claim of pixel-identical game rendering: runtime lighting/controller values,
camera, shadows and postprocessing have not all been captured from the game.
Some SIFAS base costumes contain only the face shell; missing facial geometry is
resolved automatically from original assets. Missing parts or unsupported
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
