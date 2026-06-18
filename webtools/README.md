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
| Gallery | preview body textures of bundles in a folder |

Each tool runs in **Single file** or **Batch folder** mode, shows a live log and
progress bar, and can be cancelled mid-run.

## Requirements

- Python 3.8+
- `UnityPy` (the tools install this on first run)
- `Pillow` — only needed for **Texture Importer** and **Gallery** thumbnails
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
- `modded` — `~/sukusta/modded`
- override the base with the `SUKUSTA_DIR` environment variable

## Notes

- The WebUI calls the **same** functions the command-line tools use, so output is
  identical to running the scripts directly.
- If a texture thumbnail can't be decoded (some Termux/ARM codec builds), the
  gallery just shows a "no preview" placeholder — it never crashes the server.
