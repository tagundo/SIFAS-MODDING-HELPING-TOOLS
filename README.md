# SIFAS Modding Helping Tools

A toolbox for editing **SIFAS** (*Love Live! School Idol Festival ALL STARS*)
3D model and animation files — change a character's body shape, swap costumes,
import custom textures, fix exports, sync mouth animation to lyrics, and package
your mods for sharing.

> 🇺🇸 **English** below · 🇰🇷 **한국어 설명은 [아래쪽](#한국어)에 있습니다**

**Jump to:** [English](#english) · [한국어](#한국어)

---

## English

### What is this, in plain words?

SIFAS stores everything about a character — the 3D body, the outfit, the
textures, the physics that makes hair and skirts swing — inside **asset bundle**
files (they look like `ch0107_co0001_member` and have no real file extension).
"Modding" means opening those bundles, changing something inside, and saving a
new copy.

These scripts do exactly that for the most common edits, so you don't have to
poke at raw game files by hand. Most of them open a **window with buttons**
(a graphical app); a few run as a simple text menu or a command line. **Your
original files are never overwritten** — every tool writes the result to a new
file or a separate output folder.

> ⚠️ This is an unofficial, fan-made toolkit for personal use. It is not
> affiliated with or endorsed by the makers of the game. Only use it on files
> you are allowed to modify.

### Who is this for?

- People who want to make character mods but aren't programmers.
- People who already mod and want ready-made scripts for fiddly edits
  (bone physics, mesh baking, costume transplants, lip-sync timelines).

You don't need to read or write code to use the button-based tools.

---

### Before you start (one-time setup)

1. **Install Python 3.8 or newer** from [python.org](https://www.python.org/)
   (on Windows, tick *"Add Python to PATH"* during install).
2. The button-based tools will **try to install what they need automatically**
   the first time you run them (the helper library `UnityPy`, and `Pillow` for
   images).
3. A few advanced tools also need `numpy`. If a tool complains, install the
   extras yourself in a terminal:

   ```bash
   pip install UnityPy Pillow numpy
   ```

**How to run a tool:** open a terminal in the folder where you downloaded these
files and type, for example:

```bash
python sifas_breast_tuner.py
```

On Windows you can often just **double-click** a `.py` file. On a desktop with a
screen, the tool opens its window automatically; on a phone (Termux) or a
server with no screen, the same tools fall back to a text menu.

---

### The "extracted → modded" workflow

Several tools follow one simple convention so the apps can find your files
without you typing long paths:

| Folder | What goes there |
|--------|-----------------|
| `~/sukusta/extracted` | the original, decrypted game bundles you want to edit |
| `~/sukusta/modded` | where your edited copies are saved |

On a phone with Termux these live under `~/storage/downloads/sukusta/...`.
You can point them anywhere by setting the `SUKUSTA_DIR` environment variable.
(Tools that use plain file pickers don't require this layout — you just browse
to your files.)

---

### The tools

#### 👗 Body shape & physics

| Tool | What it does for you | How it runs |
|------|----------------------|-------------|
| **`sifas_breast_tuner.py`** | Two editors in one: **Physics** changes how the chest bones jiggle (stiffness, drag, how far they swing), and **Size** changes the chest scale (set an exact size or add/subtract a little). | Window · text menu · command line |
| **`hips_size_changer.py`** | Make the hips bigger or smaller (sets the "HipsSize" scale). | Window |
| **`skirt_length_changer.py`** | Lengthen or shorten skirts by scaling the skirt's physics bones (e.g. `0.85` = shorter, `1.15` = longer). | Window · text menu |
| **`Upleg_SwingCollider_changer.py`** | Adjusts the invisible "collision balls" on the upper legs so skirts and dynamic bones don't clip through the thighs (radius and position). | Window |
| **`sifas_node_scaling.py`** | A repair tool. After transplants or FBX round-trips, parts can "teleport" out of place in live shows (a ribbon slides from the neck to the chest). This scans every body-scaling entry and fixes the mismatch while keeping the character's proportions. | Window · text menu · command line |

#### 🧥 Costumes & whole-model edits

| Tool | What it does for you | How it runs |
|------|----------------------|-------------|
| **`costume_transplant.py`** | Puts one character's **outfit onto another character** — keeps the target's face, hair and body, but gives them the donor's clothing (including extra costume bones like sailor collars or capes). Needs `numpy`. | Window · command line |
| **`unity_costumemod_packer.py`** | Bundles your finished mods into shareable installer **`.zip` packs**, each with an auto-generated thumbnail. Handles Android + iOS file pairs together. | Window · text menu |
| **`assetbundle_IosApk_batch_import_plus.py`** | Copies matching pieces from one bundle into another by their internal ID — handy for moving an edit between the **iOS and Android** versions of the same model, or grafting transplanted parts across files. | Window |

#### 🧩 Mesh & export

| Tool | What it does for you | How it runs |
|------|----------------------|-------------|
| **`sifas_mesh_baker.py`** | Permanently "bakes" a bone change (scale/rotate/move) into the actual mesh — the same idea as *Apply Armature* in Blender. Includes quick thigh presets (slim ↔ thick). Needs `numpy`. | Window · text menu · command line |
| **`fix_sifas_bundle_export.py`** | Fixes a common export bug: when you export a SIFAS body to Blender it sinks into the floor. This normalizes the bundle so **any exporter produces a correct FBX**, without changing how the model looks in-game. Needs `numpy`. | Command line: `python3 fix_sifas_bundle_export.py --in model.unity --out fixed.unity` |

#### 🎨 Textures & file naming

| Tool | What it does for you | How it runs |
|------|----------------------|-------------|
| **`texture_batch_importer.py`** | Replaces the images (textures) inside one or many bundles with your own PNG/JPG files from a folder — match by filename. Needs `Pillow`. | Window |
| **`sifas-assetbundle-renamer-by-texture.py`** | Makes a tidy copy of a folder of bundles, **renamed by the character/costume they contain** (read from the texture name), so cryptic filenames become readable. Originals are left untouched. | Window |

#### 🎤 Live-show lip-sync (`live_timeline/`)

A small **5-step pipeline** for making a character's mouth move in time with the
song's lyrics during a live performance. Run the numbered scripts in order:

1. **`1_scd-lyrics-analyzer-v4.py`** — reads the game's `.scd` lyric/timing file
   and writes out a readable list of which sound (phoneme) happens when.
2. **`2_scd_renumber_fixed.py`** — after you hand-edit that list (deleting or
   tweaking lines), this renumbers everything so it stays consistent.
3. **`3_import_to_mouth_gui4.py`** — turns the lyric sounds into mouth shapes
   (A / I / U / E / O / N) and writes them into a mouth-animation text file.
4. **`4_timeline_fixer2.py`** — cleans up animation timeline text dumps
   (smooths the blend curves, evens out fade-in/out, snaps timing to a grid).
5. **`5_unitypy_assetbundle_mouthclip_import6.py`** — writes the finished mouth
   animation back into the Unity bundle.

#### 🌐 `webtools/` — run everything from your browser

`webtools` is a small **local web app** that wraps the tools above with clicks
instead of menus — useful on a phone. It starts a tiny web server **on your own
device** (nothing is uploaded anywhere) and opens in your browser:

```bash
python -m webtools
```

Then open the address it prints (default `http://127.0.0.1:8770/`). See
[`webtools/README.md`](webtools/README.md) for full details and Termux tips.

#### 📦 `old/`

Earlier versions of some tools, kept for reference. Use the current scripts in
the main folder instead.

---

### Requirements at a glance

- **Python 3.8+**
- **`UnityPy`** — used by every bundle tool (auto-installed on first run by the
  window-based tools).
- **`Pillow`** — for images: the texture importer, packer thumbnails, gallery.
- **`numpy`** — for the mesh math tools: `costume_transplant.py`,
  `sifas_mesh_baker.py`, `fix_sifas_bundle_export.py`.

Verified against Unity 2018.4 uncompressed SIFAS model bundles.

### Tips & safety

- Always keep a backup of your original bundles. The tools write to new files,
  but backups are cheap insurance.
- If a texture preview or thumbnail can't be generated on some phones, the tool
  shows a placeholder instead of crashing.
- Bundle edits are verified to **not change how the model looks in-game** unless
  that's the whole point of the tool (size, physics, costume, etc.).

---

## 한국어

### 한마디로 무엇인가요?

SIFAS(*러브라이브! 스쿨아이돌페스티벌 ALL STARS*)는 캐릭터의 3D 몸, 의상, 텍스처,
머리·치마가 흔들리는 물리 효과까지 모두 **에셋 번들**이라는 파일 안에 담아 둡니다
(`ch0107_co0001_member` 같은 이름이고 확장자가 없습니다). "모딩(modding)"이란 이
번들을 열어 안의 내용을 바꾸고 새 파일로 저장하는 것을 말합니다.

이 스크립트들은 자주 하는 편집을 대신 해 주어서, 게임 원본 파일을 직접 손으로
뜯어볼 필요가 없게 해 줍니다. 대부분은 **버튼이 있는 창**(그래픽 앱)으로 열리고,
일부는 간단한 텍스트 메뉴나 명령어로 동작합니다. **원본 파일은 절대 덮어쓰지
않습니다** — 모든 도구는 결과를 새 파일이나 별도의 출력 폴더에 저장합니다.

> ⚠️ 이것은 비공식 팬 제작 도구이며 개인적인 용도로만 사용하세요. 게임 제작사와는
> 아무 관련이 없으며, 편집이 허용된 파일에만 사용하시기 바랍니다.

### 누구를 위한 것인가요?

- 프로그래머는 아니지만 캐릭터 모드를 만들고 싶은 분.
- 이미 모딩을 하고 있고, 까다로운 편집(본 물리, 메시 베이킹, 의상 이식, 립싱크
  타임라인 등)을 위한 완성된 스크립트가 필요한 분.

버튼 방식 도구는 코드를 읽거나 쓸 줄 몰라도 사용할 수 있습니다.

---

### 시작하기 전에 (한 번만 설정)

1. [python.org](https://www.python.org/)에서 **Python 3.8 이상**을 설치하세요
   (Windows에서는 설치 중 *"Add Python to PATH"*에 체크).
2. 버튼 방식 도구는 처음 실행할 때 **필요한 것을 자동으로 설치하려고 시도**합니다
   (도우미 라이브러리 `UnityPy`, 이미지용 `Pillow`).
3. 일부 고급 도구는 `numpy`도 필요합니다. 도구가 오류를 내면 터미널에서 직접
   설치하세요:

   ```bash
   pip install UnityPy Pillow numpy
   ```

**도구 실행 방법:** 이 파일들을 내려받은 폴더에서 터미널을 열고 예를 들어 다음과
같이 입력합니다:

```bash
python sifas_breast_tuner.py
```

Windows에서는 `.py` 파일을 **더블클릭**해도 되는 경우가 많습니다. 화면이 있는
데스크톱에서는 창이 자동으로 열리고, 화면이 없는 휴대폰(Termux)이나 서버에서는
같은 도구가 텍스트 메뉴로 대신 동작합니다.

---

### "extracted → modded" 작업 흐름

여러 도구가 긴 경로를 일일이 입력하지 않아도 파일을 찾을 수 있도록 다음의 간단한
약속을 따릅니다:

| 폴더 | 들어가는 것 |
|------|-------------|
| `~/sukusta/extracted` | 편집하려는 원본(복호화된) 게임 번들 |
| `~/sukusta/modded` | 편집한 결과물이 저장되는 곳 |

Termux 휴대폰에서는 `~/storage/downloads/sukusta/...` 아래에 위치합니다.
`SUKUSTA_DIR` 환경 변수를 지정하면 원하는 위치로 바꿀 수 있습니다. (직접 파일을
고르는 도구는 이 구조가 없어도 됩니다 — 그냥 파일을 찾아서 선택하면 됩니다.)

---

### 도구 목록

#### 👗 체형 & 물리

| 도구 | 무엇을 해 주나요 | 실행 방식 |
|------|------------------|-----------|
| **`sifas_breast_tuner.py`** | 두 편집기를 하나로: **물리**는 가슴 본이 흔들리는 방식(뻣뻣함, 저항, 흔들리는 범위)을, **크기**는 가슴 스케일(정확한 값 지정 또는 약간 더하기/빼기)을 바꿉니다. | 창 · 텍스트 메뉴 · 명령어 |
| **`hips_size_changer.py`** | 엉덩이("HipsSize" 스케일)를 키우거나 줄입니다. | 창 |
| **`skirt_length_changer.py`** | 치마 물리 본을 스케일해서 치마를 길게/짧게 합니다 (예: `0.85`=짧게, `1.15`=길게). | 창 · 텍스트 메뉴 |
| **`Upleg_SwingCollider_changer.py`** | 허벅지 위쪽의 보이지 않는 "충돌 구체"를 조정해 치마·동적 본이 허벅지를 뚫지 않게 합니다(반지름·위치). | 창 |
| **`sifas_node_scaling.py`** | 수리 도구입니다. 이식이나 FBX 왕복 후 라이브에서 일부 부위가 제자리를 벗어나 "순간이동"하는 문제(예: 리본이 목에서 가슴으로 흘러내림)를 잡아 줍니다. 모든 체형 보정 항목을 스캔해 캐릭터 비율은 유지하면서 어긋남만 고칩니다. | 창 · 텍스트 메뉴 · 명령어 |

#### 🧥 의상 & 모델 전체 편집

| 도구 | 무엇을 해 주나요 | 실행 방식 |
|------|------------------|-----------|
| **`costume_transplant.py`** | 한 캐릭터의 **의상을 다른 캐릭터에게 입힙니다** — 대상의 얼굴·머리·몸은 그대로 두고 제공자(donor)의 옷(세일러 칼라, 망토 같은 추가 의상 본 포함)만 가져옵니다. `numpy` 필요. | 창 · 명령어 |
| **`unity_costumemod_packer.py`** | 완성한 모드를 공유용 설치 **`.zip` 팩**으로 묶고, 각 팩에 썸네일을 자동 생성합니다. Android + iOS 파일 쌍도 함께 처리합니다. | 창 · 텍스트 메뉴 |
| **`assetbundle_IosApk_batch_import_plus.py`** | 내부 ID를 기준으로 한 번들의 맞는 조각을 다른 번들로 복사합니다 — 같은 모델의 **iOS·Android 버전** 사이에서 편집을 옮기거나, 이식한 부위를 파일 간에 붙일 때 유용합니다. | 창 |

#### 🧩 메시 & 내보내기

| 도구 | 무엇을 해 주나요 | 실행 방식 |
|------|------------------|-----------|
| **`sifas_mesh_baker.py`** | 본 변형(스케일/회전/이동)을 실제 메시에 영구히 "굽습니다(bake)" — Blender의 *Apply Armature*와 같은 개념입니다. 허벅지 프리셋(slim ↔ thick)도 제공합니다. `numpy` 필요. | 창 · 텍스트 메뉴 · 명령어 |
| **`fix_sifas_bundle_export.py`** | 흔한 내보내기 버그를 고칩니다: SIFAS 몸을 Blender로 내보내면 바닥에 파묻히는 현상을 바로잡아, 게임 내 모습은 그대로 둔 채 **어떤 내보내기 도구로도 올바른 FBX**가 나오게 합니다. `numpy` 필요. | 명령어: `python3 fix_sifas_bundle_export.py --in model.unity --out fixed.unity` |

#### 🎨 텍스처 & 파일 이름

| 도구 | 무엇을 해 주나요 | 실행 방식 |
|------|------------------|-----------|
| **`texture_batch_importer.py`** | 번들 안의 이미지(텍스처)를 폴더에 준비한 내 PNG/JPG 파일로 교체합니다 — 파일 이름으로 짝을 맞춥니다. `Pillow` 필요. | 창 |
| **`sifas-assetbundle-renamer-by-texture.py`** | 번들 폴더를 깔끔하게 복사하면서, 안에 든 **캐릭터/의상에 맞게 이름을 다시 붙여**(텍스처 이름에서 읽어 옴) 알아보기 쉽게 만듭니다. 원본은 건드리지 않습니다. | 창 |

#### 🎤 라이브 립싱크 (`live_timeline/`)

라이브 공연에서 캐릭터의 입 모양을 노래 가사에 맞춰 움직이게 하는 **5단계
파이프라인**입니다. 번호 순서대로 실행하세요:

1. **`1_scd-lyrics-analyzer-v4.py`** — 게임의 `.scd` 가사/타이밍 파일을 읽어
   어떤 소리(음소)가 언제 나오는지 읽기 쉬운 목록으로 만듭니다.
2. **`2_scd_renumber_fixed.py`** — 위 목록을 직접 수정(줄 삭제·조정)한 뒤, 번호를
   다시 매겨 일관성을 유지합니다.
3. **`3_import_to_mouth_gui4.py`** — 가사 소리를 입 모양(A / I / U / E / O / N)으로
   바꿔 입 애니메이션 텍스트 파일에 기록합니다.
4. **`4_timeline_fixer2.py`** — 애니메이션 타임라인 텍스트 덤프를 정리합니다
   (블렌드 커브 정리, 페이드 인/아웃 균일화, 타이밍 격자 정렬).
5. **`5_unitypy_assetbundle_mouthclip_import6.py`** — 완성된 입 애니메이션을 다시
   Unity 번들에 기록합니다.

#### 🌐 `webtools/` — 브라우저에서 모두 실행

`webtools`는 위 도구들을 메뉴 대신 클릭으로 다룰 수 있게 감싼 작은 **로컬 웹
앱**으로, 특히 휴대폰에서 편리합니다. **내 기기 안에서** 아주 작은 웹 서버를 띄우고
(어디에도 업로드되지 않습니다) 브라우저로 열립니다:

```bash
python -m webtools
```

그런 다음 출력되는 주소(기본값 `http://127.0.0.1:8770/`)를 여세요. 자세한 내용과
Termux 팁은 [`webtools/README.md`](webtools/README.md)를 참고하세요.

#### 📦 `old/`

일부 도구의 이전 버전으로, 참고용으로 보관합니다. 대신 메인 폴더의 최신
스크립트를 사용하세요.

---

### 필요한 것 한눈에 보기

- **Python 3.8 이상**
- **`UnityPy`** — 모든 번들 도구가 사용 (창 방식 도구는 처음 실행 시 자동 설치).
- **`Pillow`** — 이미지용: 텍스처 임포터, 패커 썸네일, 갤러리.
- **`numpy`** — 메시 계산 도구용: `costume_transplant.py`, `sifas_mesh_baker.py`,
  `fix_sifas_bundle_export.py`.

Unity 2018.4 비압축 SIFAS 모델 번들에서 검증되었습니다.

### 팁 & 안전

- 원본 번들은 항상 백업해 두세요. 도구가 새 파일에 쓰긴 하지만 백업은 든든한
  보험입니다.
- 일부 휴대폰에서 텍스처 미리보기·썸네일이 만들어지지 않으면, 도구는 멈추지 않고
  대체 이미지를 보여 줍니다.
- 번들 편집은 (크기·물리·의상 등 그 편집이 목적인 경우를 제외하면) **게임 내에서
  모델의 모습을 바꾸지 않도록** 검증되었습니다.
