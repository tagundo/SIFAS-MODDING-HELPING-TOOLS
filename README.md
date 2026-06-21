# SIFAS Modding Helping Tools

Tools for editing **SIFAS** (*Love Live! School Idol Festival ALL STARS*) 3D
model files — change body shape, swap costumes, import textures, fix exports,
and package mods.

**Jump to:** [English](#english) · [한국어](#한국어)

> **Language / 언어 / 言語** — the tools run in **English by default** and offer
> **한국어** and **日本語**. Pick a language from the selector in the WebUI header,
> the dropdown in a tool window, or set it once for every tool with the
> `SIFAS_LANG` environment variable (`en` / `ko` / `ja`). The choice is remembered
> between runs. Untranslated text falls back to English. See
> [Multi-language support](#multi-language-support).

---

## English

### What it is

SIFAS keeps each character's 3D body, outfit, textures and physics inside
**asset bundle** files (e.g. `ch0107_co0001_member`, no file extension). These
scripts open a bundle, change something inside, and save a new copy — the
original is left untouched.

Most tools open a window with buttons; a few run as a text menu or command line.
You don't need to write code to use the button-based ones.

### Setup

Install **Python 3.8+** ([python.org](https://www.python.org/)). The
button-based tools install what they need on first run; if a tool asks for
something, install the extras yourself:

```bash
pip install UnityPy Pillow numpy
```

Run a tool from its folder, e.g.:

```bash
python sifas_breast_tuner.py
```

On Windows you can usually double-click the `.py` file. On a desktop the window
opens automatically; on a phone (Termux) or a screenless server, the same tools
fall back to a text menu.

### The `extracted → modded` workflow

Some tools look for your files in fixed folders so you don't type long paths:

| Folder | Contents |
|--------|----------|
| `~/sukusta/extracted` | original (decrypted) bundles to edit |
| `~/sukusta/modded` | your edited copies |

On Termux these live under `~/storage/downloads/sukusta/...`. Set the
`SUKUSTA_DIR` environment variable to point elsewhere. Tools with normal file
pickers don't need this layout.

### Tools

**Body shape & physics**

| Tool | What it does | Runs as |
|------|--------------|---------|
| `sifas_breast_tuner.py` | Two editors in one: **Physics** changes how the chest bones jiggle (stiffness, drag, swing range); **Size** sets or nudges the chest scale. | window · menu · CLI |
| `hips_size_changer.py` | Make the hips bigger or smaller ("HipsSize" scale). | window |
| `skirt_length_changer.py` | Lengthen/shorten skirts by scaling their physics bones (`0.85` shorter, `1.15` longer). | window · menu |
| `Upleg_SwingCollider_changer.py` | Adjust the invisible collision spheres on the upper legs so skirts/dynamic bones don't clip through the thighs. | window |
| `sifas_node_scaling.py` | Repair tool: fixes parts that "teleport" out of place in live shows after transplants or FBX round-trips, while keeping the character's proportions. | window · menu · CLI |

**Costumes & whole-model edits**

| Tool | What it does | Runs as |
|------|--------------|---------|
| `costume_transplant.py` | Puts one character's outfit onto another — keeps the target's face/hair/body, gives them the donor's clothing (including extra costume bones). Needs `numpy`. | window · CLI |
| `unity_costumemod_packer.py` | Packs finished mods into shareable installer `.zip` packs with auto thumbnails; handles Android+iOS pairs. | window · menu |
| `assetbundle_IosApk_batch_import_plus.py` | Copies matching pieces from one bundle into another by internal ID — e.g. moving an edit between the iOS and Android versions of a model. | window |

**Mesh & export**

| Tool | What it does | Runs as |
|------|--------------|---------|
| `sifas_mesh_baker.py` | Bakes a bone change (scale/rotate/move) permanently into the mesh — like *Apply Armature* in Blender. Includes thigh presets (slim ↔ thick). Needs `numpy`. | window · menu · CLI |
| `fix_sifas_bundle_export.py` | Fixes the bug where an exported SIFAS body sinks into the floor in Blender, so any exporter produces a correct FBX (in-game look unchanged). Needs `numpy`. | CLI: `python3 fix_sifas_bundle_export.py --in model.unity --out fixed.unity` |

**Textures & file naming**

| Tool | What it does | Runs as |
|------|--------------|---------|
| `texture_batch_importer.py` | Replaces textures inside bundles with your own PNG/JPG files, matched by filename. Needs `Pillow`. | window |
| `sifas-assetbundle-renamer-by-texture.py` | Copies a folder of bundles, renamed by the character/costume they contain so cryptic names become readable. Originals untouched. | window |

**`webtools/` — run everything from your browser**

A small local web app that wraps the tools above. It runs a web server on your
own device (nothing is uploaded) and opens in your browser:

```bash
python -m webtools
```

Open the printed address (default `http://127.0.0.1:8770/`). See
[`webtools/README.md`](webtools/README.md) for details.

### Requirements

- **Python 3.8+**
- **`UnityPy`** — every bundle tool (auto-installed on first run by window tools)
- **`Pillow`** — texture importer, packer thumbnails, gallery
- **`numpy`** — `costume_transplant.py`, `sifas_mesh_baker.py`, `fix_sifas_bundle_export.py`

Verified on Unity 2018.4 uncompressed SIFAS model bundles.

These are unofficial, fan-made tools. You use them at your own responsibility.

### Multi-language support

The interfaces run in **English by default** and can switch to **한국어** or
**日本語**.

- **WebUI** (`python -m webtools`): use the language selector in the page header.
  The choice is saved in your browser.
- **Tool windows** (`sifas_breast_tuner.py`, `skirt_length_changer.py`,
  `hips_size_changer.py`, `texture_importer.py`, …): pick the language from the
  dropdown in the window. The choice is remembered for next time and shared with
  the other tools.
- **Every tool at once / scripting**: set the `SIFAS_LANG` environment variable
  to `en`, `ko` or `ja` (e.g. `SIFAS_LANG=ko python sifas_breast_tuner.py`). If
  unset, the operating-system language is used, falling back to English.

Translations are keyed by the English source text, so any string without a
translation simply shows in English. The standalone tool windows **embed their
own translations**, so each `.py` keeps working as a single self-contained file
(English / 한국어 / 日本語) even if copied out on its own; the WebUI shares one
table in [`sifas_i18n.py`](sifas_i18n.py). Some tool windows currently translate
their main interface; the remaining, less-common labels fall back to English and
are being filled in over time.

---

## 한국어

### 무엇인가요

SIFAS(*러브라이브! 스쿨아이돌페스티벌 ALL STARS*)는 캐릭터의 3D 몸·의상·텍스처·물리
효과를 **에셋 번들** 파일(예: `ch0107_co0001_member`, 확장자 없음)에 담아 둡니다.
이 스크립트들은 번들을 열어 내용을 바꾸고 새 파일로 저장합니다 — 원본은 그대로
둡니다.

대부분 버튼이 있는 창으로 열리고, 일부는 텍스트 메뉴나 명령어로 동작합니다. 버튼
방식 도구는 코드를 몰라도 사용할 수 있습니다.

### 설정

**Python 3.8 이상**을 설치하세요 ([python.org](https://www.python.org/)). 버튼 방식
도구는 처음 실행할 때 필요한 것을 설치합니다. 도구가 무언가를 요구하면 직접
설치하세요:

```bash
pip install UnityPy Pillow numpy
```

도구는 해당 폴더에서 실행합니다. 예:

```bash
python sifas_breast_tuner.py
```

Windows에서는 보통 `.py` 파일을 더블클릭하면 됩니다. 데스크톱에서는 창이 자동으로
열리고, 휴대폰(Termux)이나 화면 없는 서버에서는 같은 도구가 텍스트 메뉴로 동작합니다.

### `extracted → modded` 작업 흐름

일부 도구는 긴 경로를 입력하지 않도록 정해진 폴더에서 파일을 찾습니다:

| 폴더 | 내용 |
|------|------|
| `~/sukusta/extracted` | 편집할 원본(복호화된) 번들 |
| `~/sukusta/modded` | 편집한 결과물 |

Termux에서는 `~/storage/downloads/sukusta/...` 아래에 있습니다. `SUKUSTA_DIR` 환경
변수로 위치를 바꿀 수 있습니다. 일반 파일 선택창을 쓰는 도구는 이 구조가 필요
없습니다.

### 도구 목록

**체형 & 물리**

| 도구 | 하는 일 | 실행 방식 |
|------|---------|-----------|
| `sifas_breast_tuner.py` | 두 편집기를 하나로: **물리**는 가슴 본이 흔들리는 방식(뻣뻣함·저항·흔들림 범위)을, **크기**는 가슴 스케일을 지정/조정합니다. | 창 · 메뉴 · 명령어 |
| `hips_size_changer.py` | 엉덩이("HipsSize" 스케일)를 키우거나 줄입니다. | 창 |
| `skirt_length_changer.py` | 치마 물리 본을 스케일해 치마를 길게/짧게 합니다 (`0.85` 짧게, `1.15` 길게). | 창 · 메뉴 |
| `Upleg_SwingCollider_changer.py` | 허벅지 위쪽의 보이지 않는 충돌 구체를 조정해 치마·동적 본이 허벅지를 뚫지 않게 합니다. | 창 |
| `sifas_node_scaling.py` | 수리 도구: 이식이나 FBX 왕복 후 라이브에서 부위가 제자리를 벗어나 "순간이동"하는 문제를, 캐릭터 비율은 유지하며 고칩니다. | 창 · 메뉴 · 명령어 |

**의상 & 모델 전체 편집**

| 도구 | 하는 일 | 실행 방식 |
|------|---------|-----------|
| `costume_transplant.py` | 한 캐릭터의 의상을 다른 캐릭터에게 입힙니다 — 대상의 얼굴·머리·몸은 그대로 두고 제공자의 옷(추가 의상 본 포함)만 가져옵니다. `numpy` 필요. | 창 · 명령어 |
| `unity_costumemod_packer.py` | 완성한 모드를 공유용 설치 `.zip` 팩으로 묶고 썸네일을 자동 생성합니다. Android+iOS 쌍도 처리합니다. | 창 · 메뉴 |
| `assetbundle_IosApk_batch_import_plus.py` | 내부 ID로 한 번들의 맞는 조각을 다른 번들에 복사합니다 — 예: 같은 모델의 iOS·Android 버전 사이에서 편집 옮기기. | 창 |

**메시 & 내보내기**

| 도구 | 하는 일 | 실행 방식 |
|------|---------|-----------|
| `sifas_mesh_baker.py` | 본 변형(스케일/회전/이동)을 메시에 영구히 굽습니다 — Blender의 *Apply Armature*와 같은 개념. 허벅지 프리셋(slim ↔ thick) 포함. `numpy` 필요. | 창 · 메뉴 · 명령어 |
| `fix_sifas_bundle_export.py` | 내보낸 SIFAS 몸이 Blender에서 바닥에 파묻히는 버그를 고쳐, 어떤 도구로도 올바른 FBX가 나오게 합니다(게임 내 모습은 그대로). `numpy` 필요. | 명령어: `python3 fix_sifas_bundle_export.py --in model.unity --out fixed.unity` |

**텍스처 & 파일 이름**

| 도구 | 하는 일 | 실행 방식 |
|------|---------|-----------|
| `texture_batch_importer.py` | 번들 안 텍스처를 내 PNG/JPG 파일로 교체합니다(파일 이름으로 매칭). `Pillow` 필요. | 창 |
| `sifas-assetbundle-renamer-by-texture.py` | 번들 폴더를 복사하면서 안에 든 캐릭터/의상에 맞게 이름을 다시 붙여 알아보기 쉽게 만듭니다. 원본은 그대로. | 창 |

**`webtools/` — 브라우저에서 모두 실행**

위 도구들을 감싼 작은 로컬 웹 앱입니다. 내 기기에서 웹 서버를 띄우고(어디에도
업로드되지 않음) 브라우저로 열립니다:

```bash
python -m webtools
```

출력되는 주소(기본값 `http://127.0.0.1:8770/`)를 여세요. 자세한 내용은
[`webtools/README.md`](webtools/README.md)를 참고하세요.

### 필요한 것

- **Python 3.8 이상**
- **`UnityPy`** — 모든 번들 도구 (창 방식 도구는 첫 실행 시 자동 설치)
- **`Pillow`** — 텍스처 임포터, 패커 썸네일, 갤러리
- **`numpy`** — `costume_transplant.py`, `sifas_mesh_baker.py`, `fix_sifas_bundle_export.py`

Unity 2018.4 비압축 SIFAS 모델 번들에서 검증되었습니다.

비공식 팬 제작 도구이며, 사용에 따른 책임은 사용자에게 있습니다.
