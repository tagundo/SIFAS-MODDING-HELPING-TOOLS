"""Shared internationalisation (i18n) helpers for the SIFAS modding tools.

The tools work in **English by default**; Korean (``ko``) and Japanese (``ja``)
are offered as options.  English source strings double as the translation keys,
so any string that has no entry simply falls back to its original English text –
there is never a missing-key crash, only an untranslated string.

Active-language resolution order (first hit wins)::

    1. an explicit ``set_language()`` call made during this session
    2. the ``SIFAS_LANG`` environment variable
    3. the persisted user setting (see :func:`config_path`)
    4. the operating-system locale (``LC_ALL`` / ``LANG`` / ``locale``)
    5. ``"en"``

Desktop tools follow the process-global language and may subscribe to
:func:`on_change` so they can re-translate their widgets live.  The WebUI is
multi-user, so it never relies on the global – it passes an explicit ``lang`` to
:func:`tr` / :func:`all_strings` for every request.

Translation tables live in this single module (keyed by English source string)
so there is exactly one place to maintain them for both the desktop GUIs and the
WebUI.
"""

from __future__ import annotations

import json
import locale as _locale
import os
import threading
from pathlib import Path

# --------------------------------------------------------------------------- #
# Supported languages
# --------------------------------------------------------------------------- #
DEFAULT_LANGUAGE = "en"

# canonical code -> native display name (shown in language pickers)
LANGUAGE_NAMES = {
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
}
SUPPORTED = tuple(LANGUAGE_NAMES.keys())

# native name -> code, handy for combobox widgets
NAME_TO_CODE = {name: code for code, name in LANGUAGE_NAMES.items()}

# loose aliases accepted from env vars / OS locales (e.g. "ko_KR", "kr")
_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "ko": "ko", "kor": "ko", "kr": "ko", "korean": "ko", "한국어": "ko",
    "ja": "ja", "jpn": "ja", "jp": "ja", "japanese": "ja", "日本語": "ja",
}


def normalize(code):
    """Return a supported language code for *code*, or ``None`` if unknown.

    Accepts things like ``"ko_KR"``, ``"ja-JP"``, ``"KR"`` or a native name.
    """
    if not code:
        return None
    c = str(code).strip()
    if c in NAME_TO_CODE:                       # native display name
        return NAME_TO_CODE[c]
    c = c.replace("-", "_").lower()
    if c in _ALIASES:
        return _ALIASES[c]
    head = c.split("_", 1)[0].split(".", 1)[0]  # "ja_jp.utf-8" -> "ja"
    return _ALIASES.get(head)


# --------------------------------------------------------------------------- #
# Persisted setting
# --------------------------------------------------------------------------- #
def config_path():
    """Path of the small JSON file that remembers the user's language choice."""
    env = os.environ.get("SIFAS_TOOLS_CONFIG")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "sifas_modding_tools" / "config.json"
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "sifas_modding_tools" / "config.json"


def _read_config():
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_config(data):
    try:
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Active language
# --------------------------------------------------------------------------- #
def _detect_os_locale():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        got = normalize(os.environ.get(var))
        if got:
            return got
    try:
        got = normalize(_locale.getdefaultlocale()[0])
        if got:
            return got
    except (ValueError, IndexError):
        pass
    return None


def _detect_default():
    return (normalize(os.environ.get("SIFAS_LANG"))
            or normalize(_read_config().get("language"))
            or _detect_os_locale()
            or DEFAULT_LANGUAGE)


_lock = threading.RLock()
_current = _detect_default()
_listeners = []


def get_language():
    """The active process-global language code."""
    return _current


def set_language(code, persist=True, notify=True):
    """Set the active language; optionally persist it and notify listeners.

    Unknown codes are ignored (the previous language is kept). Returns the code
    that is in effect afterwards.
    """
    global _current
    norm = normalize(code)
    if norm is None:
        return _current
    with _lock:
        _current = norm
        if persist:
            data = _read_config()
            data["language"] = norm
            _write_config(data)
        callbacks = list(_listeners) if notify else []
    for cb in callbacks:
        try:
            cb(norm)
        except Exception:  # noqa: BLE001 - a broken listener must not break switching
            pass
    return norm


def on_change(callback):
    """Register *callback(lang)* to run after the language changes.

    Returns a zero-arg function that unsubscribes it again.
    """
    _listeners.append(callback)

    def _off():
        try:
            _listeners.remove(callback)
        except ValueError:
            pass
    return _off


# --------------------------------------------------------------------------- #
# Translation lookup
# --------------------------------------------------------------------------- #
# _TABLES[lang] maps an English source string -> its translation.
_TABLES = {}


def register(lang, mapping):
    """Merge *mapping* (English source -> translation) into *lang*'s table."""
    norm = normalize(lang)
    if norm is None or norm == DEFAULT_LANGUAGE:
        return
    _TABLES.setdefault(norm, {}).update(mapping)


def tr(text, lang=None, **fmt):
    """Translate *text* for *lang* (defaults to the active language).

    English is the implicit key and fallback, so an untranslated string returns
    unchanged. Pass keyword arguments to ``str.format`` the result, e.g.
    ``tr("Found {n} files", n=3)``.
    """
    code = normalize(lang) or (_current if lang is None else DEFAULT_LANGUAGE)
    out = text
    if code != DEFAULT_LANGUAGE:
        out = _TABLES.get(code, {}).get(text, text)
    return out.format(**fmt) if fmt else out


def all_strings(lang):
    """Return the full {English source: translation} table for *lang*.

    Used by the WebUI to ship one language's strings to the browser. For English
    (or any language without a table) an empty dict is returned, signalling the
    client to use its built-in English source text.
    """
    code = normalize(lang) or DEFAULT_LANGUAGE
    return dict(_TABLES.get(code, {}))


def language_options():
    """``[(code, native_name), ...]`` for building language pickers."""
    return [(code, LANGUAGE_NAMES[code]) for code in SUPPORTED]


# --------------------------------------------------------------------------- #
# Translation tables (English source string -> translation)
# --------------------------------------------------------------------------- #
# Korean
register("ko", {
    # -- language picker -----------------------------------------------------
    "Language": "언어",

    # -- WebUI chrome (web/index.html + web/static/app.js) -------------------
    "SIFAS Modding Tools": "SIFAS 모딩 도구",
    "Tools": "도구",
    "Gallery": "갤러리",
    "Pick a tool on the left to begin.": "왼쪽에서 도구를 선택해 시작하세요.",
    "folder of bundles...": "번들이 들어있는 폴더...",
    "Browse": "찾아보기",
    "Load": "불러오기",
    "Run": "실행",
    "Cancel": "취소",
    "Single file": "단일 파일",
    "Batch folder": "일괄(폴더)",
    "Loading…": "불러오는 중…",
    "Pick a folder first.": "먼저 폴더를 선택하세요.",
    "No bundles here.": "여기에는 번들이 없습니다.",
    "no preview": "미리보기 없음",
    "Choose": "선택",
    "Choose a folder": "폴더 선택",
    "Choose a bundle file": "번들 파일 선택",
    "Use this folder": "이 폴더 사용",
    "Running…": "실행 중…",
    "running…": "실행 중…",
    "done ✓": "완료 ✓",
    "cancelled": "취소됨",
    "error ✗": "오류 ✗",
    "Job": "작업",
    "Failed to load tools: ": "도구를 불러오지 못했습니다: ",
    "Please fill in: ": "다음 항목을 입력하세요: ",
    "Cannot open: ": "열 수 없습니다: ",
    "[cancelling…]": "[취소하는 중…]",

    # -- registry: tool labels ----------------------------------------------
    "Breast Physics (Dyna)": "가슴 물리 (Dyna)",
    "Breast Size (LiveCore)": "가슴 크기 (LiveCore)",
    "Skirt Length": "치마 길이",
    "Texture Importer": "텍스처 임포터",
    "Hips Size": "엉덩이 크기",
    "Node Scaling Fix": "노드 스케일링 수정",
    "UpLeg Swing Collider": "허벅지 Swing 콜라이더",
    "Costume Mod Packer": "코스튬 모드 패커",
    "Costume Transplant": "코스튬 이식",
    "Mesh Baker": "메시 베이커",
    "iOS/APK Selective Import": "iOS/APK 선택적 임포트",
    "Bundle Renamer (by texture)": "번들 이름변경 (텍스처 기준)",
    "Fix Bundle Export (world-space)": "번들 익스포트 수정 (월드 공간)",

    # -- registry: descriptions ---------------------------------------------
    "Edit SwingBone physics (stiffness / drag / rotation limits) on breast bones.":
        "가슴 본의 SwingBone 물리(강성 / 저항 / 회전 한계)를 편집합니다.",
    "Edit LiveCoreMemberNodeScaling.scaleValues on the BreastSize node.":
        "BreastSize 노드의 LiveCoreMemberNodeScaling.scaleValues 값을 편집합니다.",
    "Scale skirt bone Transforms to lengthen or shorten skirts.":
        "치마 본 Transform을 스케일해 치마를 길게/짧게 만듭니다.",
    "Replace Texture2D images inside bundles from a folder of PNG/JPG files.":
        "PNG/JPG 폴더의 이미지로 번들 안의 Texture2D를 교체합니다.",
    "Edit LiveCore scaling on the HipsSize node.":
        "HipsSize 노드의 LiveCore 스케일링을 편집합니다.",
    "Repair LiveCoreMemberNodeScaling entries that don't match the bone's local transform.":
        "본의 로컬 Transform과 맞지 않는 LiveCoreMemberNodeScaling 항목을 복구합니다.",
    "Edit SwingCollider radius/offset on upper-leg bones.":
        "허벅지 본의 SwingCollider 반경/오프셋을 편집합니다.",
    "Package costume bundles into installer .zip packs (with thumbnail).":
        "코스튬 번들을 설치용 .zip 팩(썸네일 포함)으로 패키징합니다.",
    "Graft a donor costume's body mesh onto a target wearer model.":
        "공여 코스튬의 바디 메시를 대상 착용 모델에 이식합니다.",
    "Bake bone scale/rotate/translate into mesh vertices.":
        "본의 스케일/회전/이동을 메시 정점에 베이크합니다.",
    "Copy matching objects from a donor into a target by pathID (iOS/APK variant transfer).":
        "pathID 기준으로 공여 번들의 일치 오브젝트를 대상에 복사합니다(iOS/APK 변형 이전).",
    "Copy bundles into a folder, renamed by their ch####_co#### texture name (originals untouched).":
        "번들을 ch####_co#### 텍스처 이름으로 변경해 폴더에 복사합니다(원본 유지).",
    "Normalize skinned meshes to world space for correct FBX export (in-game rendering unchanged).":
        "올바른 FBX 익스포트를 위해 스킨드 메시를 월드 공간으로 정규화합니다(게임 내 렌더링은 그대로).",

    # -- registry: field labels ---------------------------------------------
    "Input bundle": "입력 번들",
    "Input folder": "입력 폴더",
    "Output folder": "출력 폴더",
    "Filename prefix": "파일명 접두사",
    "Filename suffix": "파일명 접미사",
    "Bone name patterns": "본 이름 패턴",
    "low RotationLimit Δy": "low RotationLimit Δy",
    "low RotationLimit Δz": "low RotationLimit Δz",
    "high RotationLimit Δy": "high RotationLimit Δy",
    "high RotationLimit Δz": "high RotationLimit Δz",
    "Auto per-character jiggle": "캐릭터별 자동 흔들림",
    "Scale node name": "스케일 노드 이름",
    "set scale X": "스케일 설정 X",
    "set scale Y": "스케일 설정 Y",
    "set scale Z": "스케일 설정 Z",
    "add Δ X": "Δ 추가 X",
    "add Δ Y": "Δ 추가 Y",
    "add Δ Z": "Δ 추가 Z",
    "Skirt GO name patterns": "치마 GameObject 이름 패턴",
    "Image folder": "이미지 폴더",
    "Texture format": "텍스처 포맷",
    "Recurse subfolders": "하위 폴더 포함",
    "Repair mode": "복구 모드",
    "set radius": "반경 설정",
    "add radius Δ": "반경 Δ 추가",
    "set offset X": "오프셋 설정 X",
    "set offset Y": "오프셋 설정 Y",
    "set offset Z": "오프셋 설정 Z",
    "add offset Δ X": "오프셋 Δ 추가 X",
    "add offset Δ Y": "오프셋 Δ 추가 Y",
    "add offset Δ Z": "오프셋 Δ 추가 Z",
    "Output folder (zips)": "출력 폴더 (zip)",
    "Auto-detect character ID": "캐릭터 ID 자동 감지",
    "Manual character ID": "수동 캐릭터 ID",
    "Thumbnail size": "썸네일 크기",
    "Combine Android+iOS pairs": "Android+iOS 쌍 결합",
    "Donor (costume) bundle": "공여(코스튬) 번들",
    "Target (wearer) bundle": "대상(착용) 번들",
    "Preserve costume physics": "코스튬 물리 유지",
    "Realign bones": "본 재정렬",
    "Restore collision": "콜리전 복원",
    "World-space normalize": "월드 공간 정규화",
    "Fix node scaling": "노드 스케일링 수정",
    "Target spec(s)": "대상 스펙",
    "Thigh preset (FROM:TO)": "허벅지 프리셋 (FROM:TO)",
    "Recompute normals": "노멀 재계산",
    "Hierarchical skinning": "계층적 스키닝",
    "Donor bundle": "공여 번들",
    "Target bundle": "대상 번들",
    "Donor folder": "공여 폴더",
    "Target folder": "대상 폴더",
    "Import new objects (transplant grafts)": "새 오브젝트 임포트(이식 그래프트)",
    "Name include (optional)": "이름 포함 (선택)",
    "Name exclude (optional)": "이름 제외 (선택)",
    "Include costume ID": "코스튬 ID 포함",
    "Remove special characters": "특수문자 제거",
    "Filename length limit": "파일명 길이 제한",

    # -- registry: help text -------------------------------------------------
    "A single UnityFS asset bundle.": "단일 UnityFS 에셋 번들.",
    "All bundles under here are processed.": "이 폴더 아래의 모든 번들이 처리됩니다.",
    "Where modified bundles are written.": "수정된 번들이 저장될 위치.",
    "Comma/space separated SwingBone GameObject name patterns.":
        "쉼표/공백으로 구분한 SwingBone GameObject 이름 패턴.",
    "Blank = leave unchanged.": "비워두면 변경하지 않음.",
    "Detect the character and tag the output with its jiggleN tier.":
        "캐릭터를 감지해 출력 파일에 jiggleN 등급을 표시합니다.",
    "Absolute scale; blank to skip this axis.": "절대 스케일. 비워두면 이 축은 건너뜀.",
    "Absolute scale; blank to skip. Uniform 0.85 = shorter, 1.15 = longer.":
        "절대 스케일. 비워두면 건너뜀. 균일 0.85 = 짧게, 1.15 = 길게.",
    "Replacement images named after the texture (e.g. ch0107_co0001_body.png).":
        "텍스처 이름과 동일한 교체 이미지(예: ch0107_co0001_body.png).",
    "rebase = re-anchor to current local; neutralize = reset; none = scan only.":
        "rebase = 현재 로컬 기준 재설정, neutralize = 초기화, none = 검사만.",
    "Used when auto-detect is off or fails.": "자동 감지가 꺼져 있거나 실패할 때 사용됩니다.",
    "One per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1":
        "한 줄에 하나씩: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1",
    "e.g. slim:thick (optional; slim/default/thick).":
        "예: slim:thick (선택; slim/default/thick).",
    "Folder of bundles to rename.": "이름을 변경할 번들이 있는 폴더.",
    "Renamed copies go here.": "이름이 변경된 사본이 저장될 위치.",
    "Blank = no limit.": "비워두면 제한 없음.",

    # -- desktop GUI: shared vocabulary -------------------------------------
    "Single": "단일",
    "Batch": "일괄",
    "Options": "옵션",
    "Output path": "출력 경로",
    "Input dir": "입력 폴더",
    "Output dir": "출력 폴더",
    "Prefix": "접두사",
    "Suffix": "접미사",
    "Run (Single)": "실행 (단일)",
    "Run (Batch)": "실행 (일괄)",
    "Error": "오류",
    "Result": "결과",
    "Select input bundle": "입력 번들 선택",
    "Save output bundle": "출력 번들 저장",
    "Select input folder": "입력 폴더 선택",
    "Select output folder": "출력 폴더 선택",
    "Please select input bundle": "입력 번들을 선택하세요",
    "Please specify output path": "출력 경로를 지정하세요",
    "Please select input folder": "입력 폴더를 선택하세요",
    "Please specify output folder": "출력 폴더를 지정하세요",

    # -- hips_size_changer.py -----------------------------------------------
    "LiveCoreMemberNodeScaling scaler (HipsSize)": "LiveCoreMemberNodeScaling 스케일러 (HipsSize)",
    "Target GameObject name": "대상 GameObject 이름",
    "Set scaledValue (x,y,z)": "scaledValue 설정 (x,y,z)",
    "Add Δ (dx,dy,dz)": "Δ 추가 (dx,dy,dz)",

    # -- skirt_length_changer.py --------------------------------------------
    "Skirt Length Changer": "치마 길이 변경기",
    "Batch (folder)": "일괄 (폴더)",
    "Run (single)": "실행 (단일)",
    "Run (batch)": "실행 (일괄)",
    "Select folder": "폴더 선택",
    "Please set input and output paths.": "입력 및 출력 경로를 설정하세요.",
    "Please set input and output folders.": "입력 및 출력 폴더를 설정하세요.",
    "prefix": "접두사",
    "suffix": "접미사",
    "Append skirt length to filenames (e.g. _skirt085)": "파일명에 치마 길이 추가 (예: _skirt085)",
    "Skirt scale options": "치마 스케일 옵션",
    "Skirt GO name patterns (comma/space, contains match)":
        "치마 GameObject 이름 패턴 (쉼표/공백, 부분 일치)",
    "Uniform scale  (x = y = z - the usual skirt change)":
        "균일 스케일 (x = y = z - 일반적인 치마 변경)",
    "factor:": "배율:",
    "Apply": "적용",
    "Shorter 0.85": "짧게 0.85",
    "Longer 1.15": "길게 1.15",
    "Reset 1.0": "초기화 1.0",
    "Advanced - per-axis set (x, y, z)  -  blank = leave that axis":
        "고급 - 축별 설정 (x, y, z) - 비우면 해당 축 유지",
    "Advanced - add delta (dx, dy, dz)  -  added to current value":
        "고급 - 델타 추가 (dx, dy, dz) - 현재 값에 더함",
    "Skirt length/volume usually scales uniformly, so x, y, z move "
    "together. Use the factor above; the per-axis fields are for fine cases.":
        "치마 길이/볼륨은 보통 균일하게 스케일되어 x, y, z가 함께 움직입니다. "
        "위의 배율을 사용하세요. 축별 필드는 세밀한 조정용입니다.",

    # -- sifas_breast_tuner.py ----------------------------------------------
    "SIFAS Breast Tuner - Physics / Size / Both": "SIFAS 가슴 튜너 - 물리 / 크기 / 둘 다",
    "Physics (Dyna)": "물리 (Dyna)",
    "Size": "크기",
    "Both": "둘 다",
    "Library": "라이브러리",
    "Progress / Log": "진행 / 로그",
    "Clear log": "로그 지우기",
    "Save log": "로그 저장",
    "Idle": "대기 중",
    "Physics parameters": "물리 매개변수",
    "Scale parameters": "스케일 매개변수",
    "Body & physics": "바디 & 물리",
    "1. Source — pick a bundle": "1. 소스 — 번들 선택",
    "2. Mod to apply": "2. 적용할 모드",
    "3. Output → modded": "3. 출력 → modded",
    "Mod selected → modded": "선택 항목 모드 적용 → modded",
    "Y must be a number.": "Y는 숫자여야 합니다.",
    "Saved": "저장됨",
    "Log saved:\n{p}": "로그가 저장되었습니다:\n{p}",
    "Busy": "사용 중",
    "A job is already running.": "이미 작업이 실행 중입니다.",
    "Please set input/output paths.": "입력/출력 경로를 설정하세요.",
    "Please set input/output folders.": "입력/출력 폴더를 설정하세요.",
    "Scan a source folder and pick a bundle first.": "먼저 소스 폴더를 스캔하고 번들을 선택하세요.",
    "Pick a bundle.": "번들을 선택하세요.",
    "Set the modded output folder.": "modded 출력 폴더를 설정하세요.",
    "Language changed. Restart the tool to apply it.":
        "언어가 변경되었습니다. 적용하려면 도구를 다시 시작하세요.",
})

# Japanese
register("ja", {
    # -- language picker -----------------------------------------------------
    "Language": "言語",

    # -- WebUI chrome --------------------------------------------------------
    "SIFAS Modding Tools": "SIFAS Modding Tools",
    "Tools": "ツール",
    "Gallery": "ギャラリー",
    "Pick a tool on the left to begin.": "左側からツールを選んで開始してください。",
    "folder of bundles...": "バンドルのフォルダ...",
    "Browse": "参照",
    "Load": "読み込み",
    "Run": "実行",
    "Cancel": "キャンセル",
    "Single file": "単一ファイル",
    "Batch folder": "一括（フォルダ）",
    "Loading…": "読み込み中…",
    "Pick a folder first.": "先にフォルダを選んでください。",
    "No bundles here.": "ここにバンドルはありません。",
    "no preview": "プレビューなし",
    "Choose": "選択",
    "Choose a folder": "フォルダを選択",
    "Choose a bundle file": "バンドルファイルを選択",
    "Use this folder": "このフォルダを使用",
    "Running…": "実行中…",
    "running…": "実行中…",
    "done ✓": "完了 ✓",
    "cancelled": "キャンセル済み",
    "error ✗": "エラー ✗",
    "Job": "ジョブ",
    "Failed to load tools: ": "ツールの読み込みに失敗しました: ",
    "Please fill in: ": "次の項目を入力してください: ",
    "Cannot open: ": "開けません: ",
    "[cancelling…]": "[キャンセル中…]",

    # -- registry: tool labels ----------------------------------------------
    "Breast Physics (Dyna)": "胸の物理 (Dyna)",
    "Breast Size (LiveCore)": "胸のサイズ (LiveCore)",
    "Skirt Length": "スカートの長さ",
    "Texture Importer": "テクスチャインポーター",
    "Hips Size": "ヒップサイズ",
    "Node Scaling Fix": "ノードスケーリング修正",
    "UpLeg Swing Collider": "太ももSwingコライダー",
    "Costume Mod Packer": "衣装MODパッカー",
    "Costume Transplant": "衣装移植",
    "Mesh Baker": "メッシュベイカー",
    "iOS/APK Selective Import": "iOS/APK 選択インポート",
    "Bundle Renamer (by texture)": "バンドル名変更（テクスチャ基準）",
    "Fix Bundle Export (world-space)": "バンドルエクスポート修正（ワールド空間）",

    # -- registry: descriptions ---------------------------------------------
    "Edit SwingBone physics (stiffness / drag / rotation limits) on breast bones.":
        "胸ボーンのSwingBone物理（剛性 / 抵抗 / 回転制限）を編集します。",
    "Edit LiveCoreMemberNodeScaling.scaleValues on the BreastSize node.":
        "BreastSizeノードのLiveCoreMemberNodeScaling.scaleValuesを編集します。",
    "Scale skirt bone Transforms to lengthen or shorten skirts.":
        "スカートボーンのTransformをスケールして長短を調整します。",
    "Replace Texture2D images inside bundles from a folder of PNG/JPG files.":
        "PNG/JPGフォルダの画像でバンドル内のTexture2Dを置き換えます。",
    "Edit LiveCore scaling on the HipsSize node.":
        "HipsSizeノードのLiveCoreスケーリングを編集します。",
    "Repair LiveCoreMemberNodeScaling entries that don't match the bone's local transform.":
        "ボーンのローカルTransformと一致しないLiveCoreMemberNodeScaling項目を修復します。",
    "Edit SwingCollider radius/offset on upper-leg bones.":
        "太ももボーンのSwingCollider半径/オフセットを編集します。",
    "Package costume bundles into installer .zip packs (with thumbnail).":
        "衣装バンドルをインストーラー用.zipパック（サムネイル付き）にまとめます。",
    "Graft a donor costume's body mesh onto a target wearer model.":
        "提供元衣装のボディメッシュを対象の着用モデルに移植します。",
    "Bake bone scale/rotate/translate into mesh vertices.":
        "ボーンのスケール/回転/移動をメッシュ頂点にベイクします。",
    "Copy matching objects from a donor into a target by pathID (iOS/APK variant transfer).":
        "pathID基準で提供元の一致オブジェクトを対象にコピーします（iOS/APK間の移植）。",
    "Copy bundles into a folder, renamed by their ch####_co#### texture name (originals untouched).":
        "バンドルをch####_co####テクスチャ名に変更してフォルダにコピーします（原本はそのまま）。",
    "Normalize skinned meshes to world space for correct FBX export (in-game rendering unchanged).":
        "正しいFBXエクスポートのためスキンドメッシュをワールド空間に正規化します（ゲーム内描画は不変）。",

    # -- registry: field labels ---------------------------------------------
    "Input bundle": "入力バンドル",
    "Input folder": "入力フォルダ",
    "Output folder": "出力フォルダ",
    "Filename prefix": "ファイル名の接頭辞",
    "Filename suffix": "ファイル名の接尾辞",
    "Bone name patterns": "ボーン名パターン",
    "low RotationLimit Δy": "low RotationLimit Δy",
    "low RotationLimit Δz": "low RotationLimit Δz",
    "high RotationLimit Δy": "high RotationLimit Δy",
    "high RotationLimit Δz": "high RotationLimit Δz",
    "Auto per-character jiggle": "キャラ別自動ジグル",
    "Scale node name": "スケールノード名",
    "set scale X": "スケール設定 X",
    "set scale Y": "スケール設定 Y",
    "set scale Z": "スケール設定 Z",
    "add Δ X": "Δ加算 X",
    "add Δ Y": "Δ加算 Y",
    "add Δ Z": "Δ加算 Z",
    "Skirt GO name patterns": "スカートGameObject名パターン",
    "Image folder": "画像フォルダ",
    "Texture format": "テクスチャ形式",
    "Recurse subfolders": "サブフォルダを含める",
    "Repair mode": "修復モード",
    "set radius": "半径設定",
    "add radius Δ": "半径Δ加算",
    "set offset X": "オフセット設定 X",
    "set offset Y": "オフセット設定 Y",
    "set offset Z": "オフセット設定 Z",
    "add offset Δ X": "オフセットΔ加算 X",
    "add offset Δ Y": "オフセットΔ加算 Y",
    "add offset Δ Z": "オフセットΔ加算 Z",
    "Output folder (zips)": "出力フォルダ（zip）",
    "Auto-detect character ID": "キャラID自動検出",
    "Manual character ID": "手動キャラID",
    "Thumbnail size": "サムネイルサイズ",
    "Combine Android+iOS pairs": "Android+iOSペアを結合",
    "Donor (costume) bundle": "提供元（衣装）バンドル",
    "Target (wearer) bundle": "対象（着用）バンドル",
    "Preserve costume physics": "衣装の物理を保持",
    "Realign bones": "ボーン再整列",
    "Restore collision": "コリジョン復元",
    "World-space normalize": "ワールド空間で正規化",
    "Fix node scaling": "ノードスケーリング修正",
    "Target spec(s)": "対象スペック",
    "Thigh preset (FROM:TO)": "太ももプリセット (FROM:TO)",
    "Recompute normals": "法線を再計算",
    "Hierarchical skinning": "階層スキニング",
    "Donor bundle": "提供元バンドル",
    "Target bundle": "対象バンドル",
    "Donor folder": "提供元フォルダ",
    "Target folder": "対象フォルダ",
    "Import new objects (transplant grafts)": "新規オブジェクトをインポート（移植グラフト）",
    "Name include (optional)": "名前に含む（任意）",
    "Name exclude (optional)": "名前から除外（任意）",
    "Include costume ID": "衣装IDを含める",
    "Remove special characters": "特殊文字を除去",
    "Filename length limit": "ファイル名の長さ制限",

    # -- registry: help text -------------------------------------------------
    "A single UnityFS asset bundle.": "単一のUnityFSアセットバンドル。",
    "All bundles under here are processed.": "このフォルダ配下のすべてのバンドルが処理されます。",
    "Where modified bundles are written.": "変更後のバンドルの保存先。",
    "Comma/space separated SwingBone GameObject name patterns.":
        "カンマ/空白区切りのSwingBone GameObject名パターン。",
    "Blank = leave unchanged.": "空欄なら変更しません。",
    "Detect the character and tag the output with its jiggleN tier.":
        "キャラを検出し、出力にjiggleNティアを付与します。",
    "Absolute scale; blank to skip this axis.": "絶対スケール。空欄ならこの軸をスキップ。",
    "Absolute scale; blank to skip. Uniform 0.85 = shorter, 1.15 = longer.":
        "絶対スケール。空欄ならスキップ。均一0.85=短く、1.15=長く。",
    "Replacement images named after the texture (e.g. ch0107_co0001_body.png).":
        "テクスチャ名と同名の置換画像（例: ch0107_co0001_body.png）。",
    "rebase = re-anchor to current local; neutralize = reset; none = scan only.":
        "rebase=現在のローカルに再アンカー、neutralize=リセット、none=スキャンのみ。",
    "Used when auto-detect is off or fails.": "自動検出がオフ、または失敗した場合に使用します。",
    "One per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1":
        "1行に1つ: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1",
    "e.g. slim:thick (optional; slim/default/thick).":
        "例: slim:thick（任意; slim/default/thick）。",
    "Folder of bundles to rename.": "名前を変更するバンドルのフォルダ。",
    "Renamed copies go here.": "名前変更後のコピーの保存先。",
    "Blank = no limit.": "空欄なら制限なし。",

    # -- desktop GUI: shared vocabulary -------------------------------------
    "Single": "単一",
    "Batch": "一括",
    "Options": "オプション",
    "Output path": "出力パス",
    "Input dir": "入力フォルダ",
    "Output dir": "出力フォルダ",
    "Prefix": "接頭辞",
    "Suffix": "接尾辞",
    "Run (Single)": "実行（単一）",
    "Run (Batch)": "実行（一括）",
    "Error": "エラー",
    "Result": "結果",
    "Select input bundle": "入力バンドルを選択",
    "Save output bundle": "出力バンドルを保存",
    "Select input folder": "入力フォルダを選択",
    "Select output folder": "出力フォルダを選択",
    "Please select input bundle": "入力バンドルを選択してください",
    "Please specify output path": "出力パスを指定してください",
    "Please select input folder": "入力フォルダを選択してください",
    "Please specify output folder": "出力フォルダを指定してください",

    # -- hips_size_changer.py -----------------------------------------------
    "LiveCoreMemberNodeScaling scaler (HipsSize)": "LiveCoreMemberNodeScaling スケーラー (HipsSize)",
    "Target GameObject name": "対象GameObject名",
    "Set scaledValue (x,y,z)": "scaledValue設定 (x,y,z)",
    "Add Δ (dx,dy,dz)": "Δ加算 (dx,dy,dz)",

    # -- skirt_length_changer.py --------------------------------------------
    "Skirt Length Changer": "スカート丈チェンジャー",
    "Batch (folder)": "一括（フォルダ）",
    "Run (single)": "実行（単一）",
    "Run (batch)": "実行（一括）",
    "Select folder": "フォルダを選択",
    "Please set input and output paths.": "入力と出力のパスを設定してください。",
    "Please set input and output folders.": "入力と出力のフォルダを設定してください。",
    "prefix": "接頭辞",
    "suffix": "接尾辞",
    "Append skirt length to filenames (e.g. _skirt085)": "ファイル名にスカート丈を付加（例: _skirt085）",
    "Skirt scale options": "スカートスケールオプション",
    "Skirt GO name patterns (comma/space, contains match)":
        "スカートGameObject名パターン（カンマ/空白、部分一致）",
    "Uniform scale  (x = y = z - the usual skirt change)":
        "均一スケール（x = y = z - 通常のスカート変更）",
    "factor:": "倍率:",
    "Apply": "適用",
    "Shorter 0.85": "短く 0.85",
    "Longer 1.15": "長く 1.15",
    "Reset 1.0": "リセット 1.0",
    "Advanced - per-axis set (x, y, z)  -  blank = leave that axis":
        "詳細 - 軸ごとに設定 (x, y, z) - 空欄ならその軸は維持",
    "Advanced - add delta (dx, dy, dz)  -  added to current value":
        "詳細 - デルタ加算 (dx, dy, dz) - 現在値に加算",
    "Skirt length/volume usually scales uniformly, so x, y, z move "
    "together. Use the factor above; the per-axis fields are for fine cases.":
        "スカートの丈/ボリュームは通常均一にスケールし、x, y, z は一緒に動きます。"
        "上の倍率を使ってください。軸ごとのフィールドは細かい調整用です。",

    # -- sifas_breast_tuner.py ----------------------------------------------
    "SIFAS Breast Tuner - Physics / Size / Both": "SIFAS バストチューナー - 物理 / サイズ / 両方",
    "Physics (Dyna)": "物理 (Dyna)",
    "Size": "サイズ",
    "Both": "両方",
    "Library": "ライブラリ",
    "Progress / Log": "進捗 / ログ",
    "Clear log": "ログをクリア",
    "Save log": "ログを保存",
    "Idle": "待機中",
    "Physics parameters": "物理パラメータ",
    "Scale parameters": "スケールパラメータ",
    "Body & physics": "ボディ & 物理",
    "1. Source — pick a bundle": "1. ソース — バンドルを選択",
    "2. Mod to apply": "2. 適用するMOD",
    "3. Output → modded": "3. 出力 → modded",
    "Mod selected → modded": "選択をMOD適用 → modded",
    "Y must be a number.": "Y は数値である必要があります。",
    "Saved": "保存しました",
    "Log saved:\n{p}": "ログを保存しました:\n{p}",
    "Busy": "実行中",
    "A job is already running.": "すでにジョブが実行中です。",
    "Please set input/output paths.": "入力/出力パスを設定してください。",
    "Please set input/output folders.": "入力/出力フォルダを設定してください。",
    "Scan a source folder and pick a bundle first.": "先にソースフォルダをスキャンしてバンドルを選択してください。",
    "Pick a bundle.": "バンドルを選択してください。",
    "Set the modded output folder.": "modded 出力フォルダを設定してください。",
    "Language changed. Restart the tool to apply it.":
        "言語を変更しました。適用するにはツールを再起動してください。",
})
