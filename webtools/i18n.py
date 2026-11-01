"""WebUI interface translations (self-contained).

The WebUI works in English by default and can switch to Korean ("ko") or
Japanese ("ja"). English source strings are the keys and the fallback, so any
untranslated string is served as-is. This module is self-contained: the desktop
GUI tools embed their own translations separately and do not depend on it.
"""

DEFAULT_LANGUAGE = "en"

# canonical code -> native display name (display order matters)
_ORDER = ("en", "ko", "ja")
LANGUAGE_NAMES = {"en": "English", "ko": "\ud55c\uad6d\uc5b4", "ja": "\u65e5\u672c\u8a9e"}


def normalize(code):
    """Return a supported code ("en"/"ko"/"ja") or None if unrecognised."""
    if not code:
        return None
    c = str(code).strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    if c in ("en", "eng"):
        return "en"
    if c in ("ko", "kr", "kor"):
        return "ko"
    if c in ("ja", "jp", "jpn"):
        return "ja"
    return None


def language_options():
    """[(code, native_name), ...] for building a language picker."""
    return [(c, LANGUAGE_NAMES[c]) for c in _ORDER]


def tr(text, lang=None):
    """Translate *text* into *lang* (English is the key and the fallback)."""
    code = normalize(lang) or DEFAULT_LANGUAGE
    if code != DEFAULT_LANGUAGE:
        return _TABLES.get(code, {}).get(text, text)
    return text


def all_strings(lang):
    """Full {English source: translation} table for *lang* (empty for English)."""
    return dict(_TABLES.get(normalize(lang) or DEFAULT_LANGUAGE, {}))


# _TABLES[lang] maps an English source string -> its translation.
_TABLES = {
    "ko": {
        "Language": "언어",
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
        "Selected files": "선택한 파일",
        "Input bundles": "입력 번들 (여러 개)",
        "Pick several bundles; each is processed like Single.":
            "번들 여러 개를 고르세요. 각 파일이 단일과 동일하게 처리됩니다.",
        "Add file": "파일 추가",
        "No files selected.": "선택된 파일 없음.",
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
        "Choose a body part and adjust its size with a percentage. Both sides change together.": "부위를 고르고 크기를 퍼센트로 조절하세요. 좌우가 함께 바뀝니다.",
        "Example model for batch controls": "일괄 조절의 기준으로 볼 모델",
        "Choose one model from the batch folder to show the available body parts. Each file is checked again when saving.": "폴더 안의 모델 하나를 골라 조절할 수 있는 부위를 확인하세요. 저장할 때는 각 파일에 맞춰 다시 확인합니다.",
        "Adjust body parts": "부위별 크기 조절",
        "Save model": "모델 저장",
        "Costume file": "의상 파일",
        "Costume files": "의상 파일",
        "Costume folder": "의상 폴더",
        "Save folder": "저장 폴더",
        "Choose the costume model file you want to change.": "바꿀 의상 모델 파일을 선택하세요.",
        "The changed costume is saved as a new file here.": "변경한 의상을 여기에 새 파일로 저장합니다.",
        "Choose a body part": "조절할 부위 선택",
        "100% keeps the original size. Thickness controls keep the length and nearby body parts unchanged. Press Save model to write a new model file.": "100%는 원래 크기입니다. 굵기를 조절해도 길이와 인접한 부위의 크기는 유지됩니다. 모델 저장을 누르면 새 모델 파일로 저장됩니다.",
        "Expert options — individual bones and save settings": "전문가 설정 — 본 개별 조절 및 저장 설정",
        "Head size": "머리 크기",
        "Waist thickness": "허리 굵기",
        "Upper arm thickness": "위팔 굵기",
        "Forearm thickness": "아래팔 굵기",
        "Hand size": "손 크기",
        "Thigh thickness": "허벅지 굵기",
        "Calf thickness": "종아리 굵기",
        "Foot size": "발 크기",
        "Changes the head and hair together.": "머리와 머리카락을 함께 조절합니다.",
        "Changes the waist and lower torso; keeps the upper chest and shoulders the same size.": "허리와 몸통 아래쪽을 조절합니다. 가슴 위쪽과 어깨 크기는 유지됩니다.",
        "Changes both upper arms; keeps arm length and forearm thickness.": "양쪽 위팔을 조절합니다. 팔 길이와 아래팔 굵기는 유지됩니다.",
        "Changes both forearms; keeps arm length and hand size.": "양쪽 아래팔을 조절합니다. 팔 길이와 손 크기는 유지됩니다.",
        "Changes both hands, including fingers.": "손가락을 포함한 양손 크기를 조절합니다.",
        "Changes both thighs; keeps leg length and calf thickness.": "양쪽 허벅지를 조절합니다. 다리 길이와 종아리 굵기는 유지됩니다.",
        "Changes both lower legs; keeps leg length and foot size.": "양쪽 종아리를 조절합니다. 다리 길이와 발 크기는 유지됩니다.",
        "Changes both feet, including toes.": "발가락을 포함한 양발 크기를 조절합니다.",
        "Choose an input model above to enable the body controls.": "위에서 입력 모델을 고르면 부위별 조절을 사용할 수 있습니다.",
        "Original size": "원래 크기",
        "Reset": "초기화",
        "Checking the model's body parts…": "모델에서 조절할 수 있는 부위를 확인하는 중…",
        "Not available for this model.": "이 모델에서는 조절할 수 없는 부위입니다.",
        "Ready. Adjust a slider, then press Save model.": "준비되었습니다. 슬라이더를 조절한 뒤 모델 저장을 누르세요.",
        "Could not read this model. Choose a different input file.": "모델을 읽을 수 없습니다. 다른 입력 파일을 골라 주세요.",
        "Check model again": "모델 다시 확인",
        "Reset all body parts": "모든 부위 초기화",
        "Clothing attached to a body part can change with it. This tool saves a new model; it does not show a live 3D preview.": "해당 부위에 붙어 있는 의상도 함께 변할 수 있습니다. 조절 결과는 새 모델 파일로 저장되며, 실시간 3D 미리보기는 제공하지 않습니다.",
        "Choose a body part and move its slider away from 100%, then press Save model.": "조절할 부위의 슬라이더를 100%에서 바꾼 뒤 모델 저장을 눌러 주세요.",
        "Texture previews": "텍스처 미리보기",
        "View one representative texture image per costume file. Shape and mesh changes need to be checked in the game or a 3D viewer.": "의상 파일마다 대표 텍스처 이미지 한 장을 보여줍니다. 체형이나 메시를 바꾼 결과는 게임 또는 3D 뷰어에서 확인해 주세요.",
        "Reference bundle for bone list": "본 목록을 불러올 기준 번들",
        "Uses the input bundle or first selected file automatically. For batch folders, choose one representative bundle.":
            "입력 번들 또는 첫 선택 파일이 자동으로 지정됩니다. 폴더 일괄 처리 시에는 기준 번들 하나를 선택하세요.",
        "Bone transforms": "본 변형",
        "Select or type a bone, then add a transform. Scale is a multiplier; rotation is in degrees; movement uses bone-local units.":
            "본을 선택하거나 이름을 입력한 뒤 변형을 추가하세요. 크기는 배율, 회전은 도(°), 이동은 본 로컬 단위입니다.",
        "Select or type a bone": "본 선택 또는 이름 입력",
        "Bone": "본",
        "Load a bundle to see its bones, or type a bone name.": "번들을 불러와 본 목록을 확인하거나 본 이름을 입력하세요.",
        "Bones loaded. Select or type a name below.": "본 목록을 불러왔습니다. 아래에서 이름을 선택하거나 입력하세요.",
        "No skinned bones found in this bundle.": "이 번들에 스킨 본이 없습니다.",
        "Load bones": "본 불러오기",
        "Add transform": "변형 추가",
        "Remove": "삭제",
        "Scale": "크기 배율",
        "Rotation (degrees)": "회전 (도)",
        "Movement": "이동",
        "Compensate child scale": "자식 본 크기 보정",
        "Reset transform": "변형 초기화",
        "iOS/APK Selective Import": "iOS/APK 선택적 임포트",
        "Bundle Renamer (by texture)": "번들 이름변경 (텍스처 기준)",
        "Fix Bundle Export (world-space)": "번들 익스포트 수정 (월드 공간)",
        "Edit SwingBone physics (stiffness / drag / rotation limits) on breast bones.": "가슴 본의 SwingBone 물리(강성 / 저항 / 회전 한계)를 편집합니다.",
        "Edit LiveCoreMemberNodeScaling.scaleValues on the BreastSize node.": "BreastSize 노드의 LiveCoreMemberNodeScaling.scaleValues 값을 편집합니다.",
        "Scale skirt bone Transforms to lengthen or shorten skirts.": "치마 본 Transform을 스케일해 치마를 길게/짧게 만듭니다.",
        "Replace Texture2D images inside bundles from a folder of PNG/JPG files.": "PNG/JPG 폴더의 이미지로 번들 안의 Texture2D를 교체합니다.",
        "Edit LiveCore scaling on the HipsSize node.": "HipsSize 노드의 LiveCore 스케일링을 편집합니다.",
        "Repair LiveCoreMemberNodeScaling entries that don't match the bone's local transform.": "본의 로컬 Transform과 맞지 않는 LiveCoreMemberNodeScaling 항목을 복구합니다.",
        "Edit SwingCollider radius/offset on upper-leg bones.": "허벅지 본의 SwingCollider 반경/오프셋을 편집합니다.",
        "Package costume bundles into installer .zip packs (with thumbnail). Rina (209) needs BOTH the masked and no-mask bundles in one Batch run: they are detected and paired automatically by content. (If auto-pairing can't decide, name them '209rinamasked...' / '209rinaunmasked...' to pair explicitly.)":
            "코스튬 번들을 설치용 .zip 팩(썸네일 포함)으로 패키징합니다. 리나(209)는 배치 모드 한 번에 가면·노마스크 번들이 둘 다 필요합니다: 내용을 분석해 자동으로 짝지어 한 팩으로 묶습니다. (자동 판별이 안 되면 파일명을 '209rinamasked...' / '209rinaunmasked...'로 지정해 명시적으로 짝지을 수 있습니다.)",
        "Graft a donor costume's body mesh onto a target wearer model.": "공여 코스튬의 바디 메시를 대상 착용 모델에 이식합니다.",
        "Bake bone scale/rotate/translate into mesh vertices.": "본의 스케일/회전/이동을 메시 정점에 베이크합니다.",
        "Copy matching objects from a donor into a target by pathID (iOS/APK variant transfer).": "pathID 기준으로 공여 번들의 일치 오브젝트를 대상에 복사합니다(iOS/APK 변형 이전).",
        "Copy bundles into a folder, renamed by their ch####_co#### texture name (originals untouched).": "번들을 ch####_co#### 텍스처 이름으로 변경해 폴더에 복사합니다(원본 유지).",
        "Normalize skinned meshes to world space for correct FBX export (in-game rendering unchanged).": "올바른 FBX 익스포트를 위해 스킨드 메시를 월드 공간으로 정규화합니다(게임 내 렌더링은 그대로).",
        "Character Body Info": "캐릭터 신체 정보",
        "Reference: character ID, skin tone, breast size + jiggle tier, thigh type, and body scaling (Summer Splash 2020 costume; Mia/Lanzhu = Fest 3rd UR). Output appears in the log.":
            "참고용: 캐릭터 ID, 스킨톤, 가슴 크기 + jiggle 등급, 허벅지 타입, 신체 스케일링(Summer Splash 2020 코스튬; Mia/Lanzhu는 Fest 3rd UR). 결과는 로그에 표시됩니다.",
        "Character": "캐릭터",
        "All characters": "전체 캐릭터",
        "Accessory Un-clip": "액세서리 클리핑 해제",
        "Skin Tone Changer": "스킨톤 변경",
        "Costume Part Transplant": "코스튬 부분 이식",
        "Lower Body Swap": "하체 교체",
        "Stop accessories transplanted onto a resized body from sinking in (lifts chest ornaments to match the bust).":
            "리사이즈된 바디에 이식한 액세서리가 파묻히는 것을 방지합니다(가슴 장식을 버스트에 맞춰 올림).",
        "Recolour a body/hand texture image from one official skin-tone class to another (works on PNG images, not bundles).":
            "바디/핸드 텍스처 이미지의 스킨톤을 공식 톤 클래스 간에 변경합니다(번들이 아닌 PNG 이미지 대상).",
        "Move ONE costume part (wings / tail / cape) from a donor model onto a target wearer.":
            "코스튬의 한 부분(날개/꼬리/망토)만 공여 모델에서 대상 착용자에게 옮깁니다.",
        "Graft a good lower body from a donor onto a target that has deleted hip/thigh skin (the 'detached thighs' fix).":
            "하체 스킨이 삭제된 대상에 공여의 정상 하체를 이식합니다('허벅지 분리' 수정).",
        # Accessory Un-clip
        "Lift strength": "올림 강도",
        "1.0 = match the bust exactly.": "1.0 = 버스트에 정확히 맞춤.",
        "Min bust overlap": "최소 버스트 겹침",
        "Only lift parts overlapping the bust by at least this fraction.":
            "버스트와 이 비율 이상 겹치는 부분만 올립니다.",
        "Also pull in when shrunk": "축소 시에도 끌어당기기",
        "Force anchors (optional)": "앵커 강제 지정 (선택)",
        "Comma-separated bone names to force; blank = auto-detect.":
            "강제할 본 이름(쉼표 구분); 비우면 자동 감지.",
        # Skin Tone Changer
        "Input image": "입력 이미지",
        "A texture PNG/JPG (not a bundle).": "텍스처 PNG/JPG (번들 아님).",
        "From tone": "원본 톤",
        "To tone": "대상 톤",
        "auto = detect from the image.": "auto = 이미지에서 자동 감지.",
        "Skin only (keep costume colours)": "피부만 (의상 색상 유지)",
        "Strength (0–1)": "강도 (0–1)",
        # Costume Part Transplant
        "Donor bundle (has the part)": "공여 번들 (해당 부분 보유)",
        "Target bundle (wearer)": "대상 번들 (착용자)",
        "Part root bone (optional)": "부분 루트 본 (선택)",
        "Part root bone": "부분 루트 본",
        "(auto — biggest part)": "(자동 — 가장 큰 부분)",
        "loading…": "불러오는 중…",
        "Costume Recolour (irochi)": "의상 리컬러(이로치)",
        "Base costume model bundle": "기본 의상 모델 번들",
        "Colour-variant texture bundle (irochi)": "색상 변형 텍스처 번들(이로치)",
        "Pick a part from the donor bundle (press Load to read its parts). Blank / auto = the biggest costume-specific part.":
            "도너 번들에서 부분을 선택하세요(불러오기를 누르면 부분 목록을 읽습니다). 비움/자동 = 가장 큰 의상 전용 부분.",
        "Named band presets, like the desktop tool. 'Custom' uses the Cut low/high Y + Region fields below. Y guide: ankle .11 · calf .30 · knee .50 · thigh .67 · crotch .85 · belly .92 · waist 1.05.":
            "데스크톱 도구처럼 이름 붙은 밴드 프리셋. 'Custom'은 아래의 하단/상단 Y + 영역 필드를 사용합니다. Y 가이드: 발목 .11 · 종아리 .30 · 무릎 .50 · 허벅지 .67 · 사타구니 .85 · 아랫배 .92 · 허리 1.05.",
        "Which bones may be replaced (used when Cut preset = Custom). 'lower' keeps the target's torso; 'lower_belly'/'central' reach up into the belly.":
            "교체할 수 있는 본(Cut 프리셋 = Custom일 때 사용). 'lower'는 대상 상체를 유지하고, 'lower_belly'/'central'은 아랫배까지 올라갑니다.",
        "Used when Cut preset = Custom. World-space Y of the lower cut; blank = floor. e.g. 0.50 = knee.":
            "Cut 프리셋 = Custom일 때 사용. 하단 절단의 월드 공간 Y; 비우면 바닥. 예: 0.50 = 무릎.",
        "Used when Cut preset = Custom. Blank = no upper limit. e.g. 0.96 = just below waist.":
            "Cut 프리셋 = Custom일 때 사용. 비우면 상한 없음. 예: 0.96 = 허리 바로 아래.",
        "Keep only the donor's main body component (drops a thigh dagger, garter rings). Turn OFF if the donor's hips/thighs are a SEPARATE mesh piece and got left out (a cause of 'nothing to graft').":
            "도너의 메인 몸통 컴포넌트만 유지(허벅지 단검, 가터 링 등 제거). 도너의 엉덩이/허벅지가 별도 메시 조각이라 빠졌다면 끄세요('이식할 것 없음'의 원인).",
        "Raise the cap's rim on every side (used together with the lift above).":
            "캡 가장자리를 모든 방향으로 올림(위의 리프트와 함께 사용).",
        "Report the drop/take triangle counts without writing — use to diagnose 'nothing to graft'.":
            "쓰지 않고 제거/가져올 삼각형 수만 보고 — '이식할 것 없음' 진단에 사용.",
        "Apply a colour-variant (irochi) texture bundle onto its base costume model, so the model shows the alt colour (the _cN textures are a separate texture-only bundle in SIFAS).":
            "색상 변형(이로치) 텍스처 번들을 기본 의상 모델에 적용해 모델이 대체 색으로 보이게 합니다(SIFAS에서 _cN 텍스처는 별도의 텍스처 전용 번들입니다).",
        "The full model bundle (has the mesh + base textures chXXXX_coYYYY_body/head).":
            "풀 모델 번들(메시 + 기본 텍스처 chXXXX_coYYYY_body/head 포함).",
        "The texture-only bundle with the _cN textures (chXXXX_coYYYY_body_c1 …). Must be the SAME costume as the base.":
            "_cN 텍스처가 든 텍스처 전용 번들(chXXXX_coYYYY_body_c1 …). 기본과 반드시 같은 의상이어야 합니다.",
        "Folder of decrypted bundles": "복호화된 번들 폴더",
        "Auto-pairs every texture-only colour variant (_cN) with its complete model by the chXXXX_coYYYY code INSIDE the bundles and composites them all — no need to pick pairs. Just decrypt a costume pair (or a whole batch) into a folder and point here.":
            "각 텍스처 전용 색상 변형(_cN)을, 번들 내부의 chXXXX_coYYYY 코드로 완성 모델과 자동으로 짝지어 전부 합성합니다 — 짝을 직접 고를 필요 없음. 의상 쌍(또는 여러 개)을 폴더에 복호화해 넣고 여기를 지정하세요.",
        "e.g. Wing_L_00; blank = auto-detect the biggest costume-specific part.":
            "예: Wing_L_00; 비우면 가장 큰 코스튬 전용 부분을 자동 감지.",
        "Preserve part physics": "부분 물리 유지",
        "Patch part texture onto target atlas": "부분 텍스처를 대상 아틀라스에 패치",
        # Lower Body Swap
        "Donor bundle (good lower body)": "공여 번들 (정상 하체)",
        "Target bundle (to fix)": "대상 번들 (수정할 대상)",
        "Region": "영역",
        "Cut low Y (optional)": "하단 절단 Y (선택)",
        "World-space Y of the lower cut; blank = floor. e.g. 0.50 = knee.":
            "하단 절단의 월드 공간 Y; 비우면 바닥. 예: 0.50 = 무릎.",
        "Cut high Y (optional)": "상단 절단 Y (선택)",
        "Blank = no upper limit. e.g. 0.96 = just below waist.":
            "비우면 상한 없음. 예: 0.96 = 허리 바로 아래.",
        "Exclude donor accessories": "공여 액세서리 제외",
        "Cut preset": "절단 프리셋",
        "Fix detached thighs (hip/crotch) — recommended": "분리된 허벅지 수정 (엉덩이/사타구니) — 권장",
        "Thigh & up (keep calf/shoes)": "허벅지 이상 (종아리/신발 유지)",
        "Calf part & up": "종아리 일부 이상",
        "From calf & up (keep feet)": "종아리부터 위로 (발 유지)",
        "Whole lower body": "하체 전체",
        "Custom range (use Cut low/high Y below)": "사용자 지정 범위 (아래 Y 값 사용)",
        "Region (custom only)": "영역 (사용자 지정 시)",
        "Cut low Y (custom)": "하단 절단 Y (사용자 지정)",
        "Cut high Y (custom)": "상단 절단 Y (사용자 지정)",
        "Cap edge lift — all sides": "캡 가장자리 리프트 — 전체",
        "Cap edge — front (blank = all)": "캡 가장자리 — 앞 (비우면 전체)",
        "Cap edge — back (blank = all)": "캡 가장자리 — 뒤 (비우면 전체)",
        "Cap edge — left (blank = all)": "캡 가장자리 — 좌 (비우면 전체)",
        "Cap edge — right (blank = all)": "캡 가장자리 — 우 (비우면 전체)",
        "Merge rim map too": "림 맵도 병합",
        "Generate mipmaps": "밉맵 생성",
        "Dry run (no write)": "드라이 런 (쓰지 않음)",
        # Breast physics parameter labels
        "stiffnessForce": "강성 (stiffnessForce)",
        "dragForce": "저항 (dragForce)",
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
        "set scale": "스케일 설정",
        "add Δ": "Δ 추가",
        "set offset": "오프셋 설정",
        "add offset Δ": "오프셋 Δ 추가",
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
        # costume transplant - desktop GUI parity (translations from costume_transplant.py)
        "Preserve appendage jiggle physics (collar / tie / wings)":
            "부속물 흔들림 물리 유지 (옷깃 / 넥타이 / 날개)",
        "Restore body collision for those bones": "해당 본의 바디 콜리전 복원",
        "Only takes effect when appendage jiggle physics is preserved.":
            "부속물 흔들림 물리 유지가 켜져 있을 때만 적용됩니다.",
        "Realign body bones to the costume's rest pose (fixes offset ribbon/skirt)":
            "바디 본을 코스튬의 기본 포즈에 재정렬 (어긋난 리본/치마 보정)",
        "World-space the body mesh (so swinging ribbon/skirt render correctly)":
            "바디 메시를 월드 공간으로 (흔들리는 리본/치마가 올바르게 렌더링되도록)",
        "Re-anchor NodeScaling to realigned bones (keeps body shaping; stops the in-game ribbon dropping to the chest)":
            "재정렬된 본에 NodeScaling 재고정 (체형 유지; 게임 내 리본이 가슴으로 처지는 현상 방지)",
        "Use the donor's swing physics for shared costume parts (skirt / ribbon) — the bust always stays the wearer's":
            "공유 코스튬 부위(치마 / 리본)에 공여의 스윙 물리 사용 — 가슴은 항상 착용자 것 유지",
        "Special handling for masked / board-face models (Rina-chan board): auto-detect, protect head + body-shape scaling":
            "마스크 / 보드 얼굴 모델(리나쨩 보드) 특수 처리: 자동 감지, 머리 + 체형 스케일링 보호",
        "Transplant without the body textures (keep the wearer's own texture; only the costume mesh + bones are grafted)":
            "바디 텍스처 없이 이식 (착용자의 텍스처 유지; 코스튬 메시 + 본만 이식)",
        "Scale swing physics to a body-scaled target (keeps skirt/ribbon/wing/tail proportions on the Rina board; no-op on normal targets)":
            "체형 스케일된 대상에 스윙 물리 스케일 (리나 보드에서 치마/리본/날개/꼬리 비율 유지; 일반 대상엔 영향 없음)",
        "Match thigh to target character": "허벅지를 대상 캐릭터에 맞춤",
        "Scale the costume's thighs from the donor's body type to the target's (mesh baker).":
            "의상의 허벅지를 공여 캐릭터 체형에서 대상 체형으로 스케일합니다 (메시 베이커).",
        "Match skin tone to target character": "스킨톤을 대상 캐릭터에 맞춤",
        "Recolour the body skin from the donor's tone to the wearer's, so the transplanted costume shows the target character's skin (skin tone changer). On by default — turn it off to keep the donor's original skin. It covers the whole skin now; the shift lands on the target's official tone class (same as the standalone Skin Tone Changer).":
            "이식한 의상에 대상 캐릭터의 피부가 나오도록, 바디 스킨을 공여 캐릭터의 톤에서 착용 캐릭터의 톤으로 재색상화합니다(스킨톤 변경). 기본 켜짐 — 끄면 공여자의 원래 피부를 유지합니다. 이제 피부 전체를 덮으며, 변화량은 대상의 공식 톤 클래스까지 이동합니다(스탠드얼론 Skin Tone Changer와 동일).",
        "Donor skin tone": "공여 스킨톤",
        "auto = the donor character's official tone (pixel detection only when that is unknown). Set explicitly if the donor bundle was already recoloured.":
            "auto = 공여 캐릭터의 공식 톤 (알 수 없을 때만 픽셀에서 감지). 공여 번들이 이미 재색상화된 경우 직접 지정하세요.",
        # --- desktop-parity options added to existing tools ---
        "Blank = leave unchanged. Desktop default 0.02 (the Soft feel).":
            "비우면 변경 안 함. 데스크톱 기본값 0.02 (Soft 느낌).",
        "Blank = leave unchanged. Desktop default 0.3 (the Soft feel).":
            "비우면 변경 안 함. 데스크톱 기본값 0.3 (Soft 느낌).",
        "Edit entries (advanced, single-file)": "항목 편집 (고급, 단일 파일)",
        "One per line, same grammar as the desktop --set: 'Bone;scaled=x,y,z;origin=x,y,z;kind=pos'. Edits existing entries. Ignored in batch (auto-repair only).":
            "한 줄에 하나, 데스크톱 --set 과 동일한 문법: 'Bone;scaled=x,y,z;origin=x,y,z;kind=pos'. 기존 항목을 편집합니다. 배치에서는 무시(자동 수리만).",
        "Add entries (advanced, single-file)": "항목 추가 (고급, 단일 파일)",
        "One per line, same grammar as the desktop --add: 'Bone;scaled=x,y,z;kind=scale'. Adds a new entry for another bone (kind defaults to scale; origin defaults to the bone's current local).":
            "한 줄에 하나, 데스크톱 --add 와 동일한 문법: 'Bone;scaled=x,y,z;kind=scale'. 다른 본에 새 항목을 추가합니다(kind 기본 scale, origin 기본은 본의 현재 local).",
        "clamp radius min": "반경 클램프 최소",
        "Blank = no lower bound.": "비우면 하한 없음.",
        "clamp radius max": "반경 클램프 최대",
        "Blank = no upper bound.": "비우면 상한 없음.",
        "clamp offset min": "오프셋 클램프 최소",
        "Per-axis lower bound; blank = free.": "축별 하한; 비우면 제한 없음.",
        "clamp offset max": "오프셋 클램프 최대",
        "Per-axis upper bound; blank = free.": "축별 상한; 비우면 제한 없음.",
        "Spine compensation target": "스파인 보정 대상",
        "Which child bone absorbs the inverse scale for compensated Spine* targets. Only affects Spine* bakes.":
            "보정된 Spine* 타깃에서 역스케일을 흡수할 자식 본. Spine* 베이크에만 영향.",
        "Spine2 (widens Spine+Spine1)": "Spine2 (Spine+Spine1 확장)",
        "Spine1": "Spine1",
        "Spine1 + Spine2": "Spine1 + Spine2",
        "Auto": "자동",
        "Include hidden meshes (foot_shadow · Hair · Face)": "숨은 메시 포함 (foot_shadow · Hair · Face)",
        "Only these meshes (advanced)": "이 메시만 (고급)",
        "Comma/newline separated mesh names; blank = all skinned, non-hidden meshes.":
            "쉼표/줄바꿈으로 구분한 메시 이름; 비우면 숨겨지지 않은 모든 스킨 메시.",
        "Objects whose m_Name matches are left as the target's (protects the wearer's face/head + shadows). Desktop default shown.":
            "m_Name 이 일치하는 오브젝트는 대상 것으로 유지(착용자의 얼굴/머리 + 그림자 보호). 데스크톱 기본값 표시.",
        "Script class exclude (MonoBehaviour)": "스크립트 클래스 제외 (MonoBehaviour)",
        "Donor MonoBehaviours of these script classes are not copied, so the wearer keeps its own swing physics. Desktop default shown.":
            "이 스크립트 클래스의 공여 MonoBehaviour 는 복사하지 않아 착용자가 자신의 스윙 물리를 유지합니다. 데스크톱 기본값 표시.",
        "Digit-agnostic name matching": "숫자 무시 이름 매칭",
        "Treat digits as wildcards, so ch0001_* matches any character id.":
            "숫자를 와일드카드로 처리하여 ch0001_* 가 모든 캐릭터 ID 에 일치.",
        "Name match mode": "이름 매칭 모드",
        "Remove original filename completely": "원본 파일명 완전 제거",
        "Name purely from the texture; collisions are auto-numbered so nothing is overwritten.":
            "텍스처만으로 이름 생성; 충돌 시 자동 번호로 덮어쓰기 방지.",
        "Add the part as its own sub-mesh + material (keep its texture)":
            "부위를 자체 서브메시 + 머티리얼로 추가 (텍스처 유지)",
        "World-space the body mesh (so swinging parts render correctly)":
            "바디 메시를 월드 공간으로 (흔들리는 부위가 올바르게 렌더링되도록)",
        "Re-anchor NodeScaling (keep the wearer's body shaping)":
            "NodeScaling 재고정 (착용자의 체형 유지)",
        "Open skirt cap lift (0 = off)": "열린 치마 캡 리프트 (0 = 끔)",
        "Lift the open cap so a shorter donor lower body doesn't leave a hole; 0 = flat cap.":
            "짧은 공여 하체가 구멍을 남기지 않도록 열린 캡을 들어올림; 0 = 평평한 캡.",
        "Recolour skin only": "피부만 재색상화",
        "Restrict the recolour to the skin region, using the mesh's bone weights when available (excludes skirt / sleeves / ribbon / accessories) and never dropping real skin. NOTE: torso-tight clothing on body bones (a bodice) can't be told from chest skin, so its colour may still shift. For an exact result, export the texture and edit it with the Skin Tone Changer. On by default on the phone app, off on desktop.":
            "재색상화를 피부 영역으로 제한합니다. 가능하면 메시의 본 가중치를 사용해(치마/소매/리본/악세서리 제외) 실제 피부는 절대 빠뜨리지 않습니다. 주의: 몸통 본에 밀착된 옷(보디스)은 가슴 피부와 구분이 안 되어 색이 변할 수 있습니다. 정확한 결과를 원하면 텍스처를 export 후 스킨톤 변경 도구로 직접 수정하세요. 폰 앱에서는 기본 켜짐, 데스크톱에서는 기본 꺼짐.",
        "Also restrict by skin colour": "스킨색으로도 제한",
        "Additionally require skin-like colour, so non-skin-coloured body-bone clothing (e.g. a blue bodice) is left alone. May drop deeply shadowed skin — leave off if any real skin gets missed.":
            "스킨색 조건을 추가로 요구해, 스킨색이 아닌 몸통 본 의상(예: 파란 보디스)은 건드리지 않습니다. 짙게 그늘진 피부는 빠질 수 있으니, 실제 피부가 누락되면 끄세요.",
        "Target spec(s)": "대상 스펙",
        "Target spec(s) — advanced": "대상 스펙 — 고급",
        "Thigh preset": "허벅지 프리셋",
        "Physics feel (preset)": "물리 느낌 (프리셋)",
        "Size preset (by character)": "크기 프리셋 (캐릭터별)",
        "Length preset": "길이 프리셋",
        "One-click thigh resize: scales both UpLeg bones with child compensation.":
            "원클릭 허벅지 크기조절: 양쪽 UpLeg 본을 자식 보정과 함께 스케일합니다.",
        "Optional manual bones, one per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1":
            "선택: 수동 본, 한 줄에 하나씩: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1",
        "Fills stiffnessForce / dragForce below; you can still fine-tune.":
            "아래 stiffnessForce / dragForce를 채웁니다. 직접 미세조정도 가능합니다.",
        "Fills the X/Y/Z scale below with a character's in-game breast size.":
            "아래 X/Y/Z 스케일을 캐릭터의 인게임 가슴 크기로 채웁니다.",
        "Skirts usually scale uniformly; this fills X/Y/Z together.":
            "치마는 보통 균일하게 스케일됩니다. X/Y/Z를 함께 채웁니다.",
        "(custom)": "(직접 입력)",
        "Softer (0.01 / 0.2)": "더 부드럽게 (0.01 / 0.2)",
        "Soft (0.02 / 0.3)": "부드럽게 (0.02 / 0.3)",
        "Firm (0.05 / 0.5)": "탄탄하게 (0.05 / 0.5)",
        "Shorter (0.85)": "짧게 (0.85)",
        "Longer (1.15)": "길게 (1.15)",
        "Reset (1.0)": "초기화 (1.0)",
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
        "A single UnityFS asset bundle.": "단일 UnityFS 에셋 번들.",
        "All bundles under here are processed.": "이 폴더 아래의 모든 번들이 처리됩니다.",
        "Where modified bundles are written.": "수정된 번들이 저장될 위치.",
        "Comma/space separated SwingBone GameObject name patterns.": "쉼표/공백으로 구분한 SwingBone GameObject 이름 패턴.",
        "Blank = leave unchanged.": "비워두면 변경하지 않음.",
        "Detect the character and tag the output with its jiggleN tier.": "캐릭터를 감지해 출력 파일에 jiggleN 등급을 표시합니다.",
        "Auto jiggle": "자동 jiggle",
        "Off": "끄기",
        "Match current breast size": "현재 가슴 크기에 맞춤",
        "Follow character (stock)": "캐릭터 기본값 따라가기",
        "Match current breast size = follow the size already in the bundle (best after resizing). Follow character = the character's stock tier.":
            "현재 가슴 크기에 맞춤 = 번들에 이미 적용된 크기를 따릅니다(리사이즈 후 권장). 캐릭터 기본값 = 캐릭터의 기본 tier.",
        "Defaults to the installer's suit/ drop folder, so Install Costume picks the pack up right away.":
            "설치 도구의 suit/ 드롭 폴더가 기본값이라 Install Costume이 바로 팩을 인식합니다.",
        "Absolute scale; blank to skip this axis.": "절대 스케일. 비워두면 이 축은 건너뜀.",
        "Absolute scale; blank to skip. Uniform 0.85 = shorter, 1.15 = longer.": "절대 스케일. 비워두면 건너뜀. 균일 0.85 = 짧게, 1.15 = 길게.",
        "Replacement images named after the texture (e.g. ch0107_co0001_body.png).": "텍스처 이름과 동일한 교체 이미지(예: ch0107_co0001_body.png).",
        "In the phone app pick RGBA32 (uncompressed) or an ASTC format (what SIFAS uses — encoded on-device). ETC/DXT/BC and Keep Original need the desktop tools.":
            "폰 앱에서는 RGBA32(비압축 — 기기에서 작동)를 고르세요. 압축 포맷(ASTC/ETC/DXT)과 Keep Original은 데스크톱 도구가 필요합니다.",
        "rebase = re-anchor to current local; neutralize = reset; none = scan only.": "rebase = 현재 로컬 기준 재설정, neutralize = 초기화, none = 검사만.",
        "Used when auto-detect is off or fails.": "자동 감지가 꺼져 있거나 실패할 때 사용됩니다.",
        "One per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1": "한 줄에 하나씩: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1",
        "e.g. slim:thick (optional; slim/default/thick).": "예: slim:thick (선택; slim/default/thick).",
        "Folder of bundles to rename.": "이름을 변경할 번들이 있는 폴더.",
        "Renamed copies go here.": "이름이 변경된 사본이 저장될 위치.",
        "Blank = no limit.": "비워두면 제한 없음.",
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
        "LiveCoreMemberNodeScaling scaler (HipsSize)": "LiveCoreMemberNodeScaling 스케일러 (HipsSize)",
        "Target GameObject name": "대상 GameObject 이름",
        "Set scaledValue (x,y,z)": "scaledValue 설정 (x,y,z)",
        "Add Δ (dx,dy,dz)": "Δ 추가 (dx,dy,dz)",
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
        "Skirt GO name patterns (comma/space, contains match)": "치마 GameObject 이름 패턴 (쉼표/공백, 부분 일치)",
        "Uniform scale  (x = y = z - the usual skirt change)": "균일 스케일 (x = y = z - 일반적인 치마 변경)",
        "factor:": "배율:",
        "Apply": "적용",
        "Shorter 0.85": "짧게 0.85",
        "Longer 1.15": "길게 1.15",
        "Reset 1.0": "초기화 1.0",
        "Advanced - per-axis set (x, y, z)  -  blank = leave that axis": "고급 - 축별 설정 (x, y, z) - 비우면 해당 축 유지",
        "Advanced - add delta (dx, dy, dz)  -  added to current value": "고급 - 델타 추가 (dx, dy, dz) - 현재 값에 더함",
        "Skirt length/volume usually scales uniformly, so x, y, z move together. Use the factor above; the per-axis fields are for fine cases.": "치마 길이/볼륨은 보통 균일하게 스케일되어 x, y, z가 함께 움직입니다. 위의 배율을 사용하세요. 축별 필드는 세밀한 조정용입니다.",
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
        "Language changed. Restart the tool to apply it.": "언어가 변경되었습니다. 적용하려면 도구를 다시 시작하세요."
    },
    "ja": {
        "Language": "言語",
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
        "Selected files": "選択したファイル",
        "Input bundles": "入力バンドル（複数）",
        "Pick several bundles; each is processed like Single.":
            "バンドルを複数選択してください。各ファイルはSingleと同様に処理されます。",
        "Add file": "ファイルを追加",
        "No files selected.": "選択されたファイルはありません。",
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
        "Choose a body part and adjust its size with a percentage. Both sides change together.": "部位を選び、サイズをパーセントで調整します。左右をまとめて変更できます。",
        "Example model for batch controls": "一括調整の基準モデル",
        "Choose one model from the batch folder to show the available body parts. Each file is checked again when saving.": "フォルダー内のモデルを1つ選んで調整可能な部位を確認します。保存時には各ファイルの構造を確認します。",
        "Adjust body parts": "部位別のサイズ調整",
        "Save model": "モデルを保存",
        "Costume file": "衣装ファイル",
        "Costume files": "衣装ファイル",
        "Costume folder": "衣装フォルダー",
        "Save folder": "保存先フォルダー",
        "Choose the costume model file you want to change.": "変更する衣装モデルファイルを選んでください。",
        "The changed costume is saved as a new file here.": "変更した衣装を新しいファイルとして保存します。",
        "Choose a body part": "調整する部位を選択",
        "100% keeps the original size. Thickness controls keep the length and nearby body parts unchanged. Press Save model to write a new model file.": "100%は元のサイズです。太さの調整では長さと隣接部位のサイズを保ちます。モデルを保存を押すと新しいモデルファイルが保存されます。",
        "Expert options — individual bones and save settings": "詳細設定 — ボーンごとの調整と保存設定",
        "Head size": "頭のサイズ",
        "Waist thickness": "腰の太さ",
        "Upper arm thickness": "上腕の太さ",
        "Forearm thickness": "前腕の太さ",
        "Hand size": "手のサイズ",
        "Thigh thickness": "太ももの太さ",
        "Calf thickness": "ふくらはぎの太さ",
        "Foot size": "足のサイズ",
        "Changes the head and hair together.": "頭と髪をまとめて調整します。",
        "Changes the waist and lower torso; keeps the upper chest and shoulders the same size.": "腰と胴体の下部を調整します。胸の上部と肩のサイズを保ちます。",
        "Changes both upper arms; keeps arm length and forearm thickness.": "両上腕を調整します。腕の長さと前腕の太さを保ちます。",
        "Changes both forearms; keeps arm length and hand size.": "両前腕を調整します。腕の長さと手のサイズを保ちます。",
        "Changes both hands, including fingers.": "指を含む両手のサイズを調整します。",
        "Changes both thighs; keeps leg length and calf thickness.": "両太ももを調整します。脚の長さとふくらはぎの太さを保ちます。",
        "Changes both lower legs; keeps leg length and foot size.": "両ふくらはぎを調整します。脚の長さと足のサイズを保ちます。",
        "Changes both feet, including toes.": "足指を含む両足のサイズを調整します。",
        "Choose an input model above to enable the body controls.": "上で入力モデルを選ぶと部位別の調整を利用できます。",
        "Original size": "元のサイズ",
        "Reset": "リセット",
        "Checking the model's body parts…": "調整できる部位を確認中…",
        "Not available for this model.": "このモデルでは調整できません。",
        "Ready. Adjust a slider, then press Save model.": "準備ができました。スライダーを調整してモデルを保存を押してください。",
        "Could not read this model. Choose a different input file.": "モデルを読み込めません。別の入力ファイルを選んでください。",
        "Check model again": "モデルを再確認",
        "Reset all body parts": "すべての部位をリセット",
        "Clothing attached to a body part can change with it. This tool saves a new model; it does not show a live 3D preview.": "部位に付いている衣装も一緒に変わることがあります。新しいモデルファイルを保存するツールで、リアルタイム3Dプレビューは表示しません。",
        "Choose a body part and move its slider away from 100%, then press Save model.": "調整する部位のスライダーを100%から変更してモデルを保存を押してください。",
        "Texture previews": "テクスチャプレビュー",
        "View one representative texture image per costume file. Shape and mesh changes need to be checked in the game or a 3D viewer.": "衣装ファイルごとに代表的なテクスチャ画像を1枚表示します。体形やメッシュの変更はゲームまたは3Dビューアーで確認してください。",
        "Reference bundle for bone list": "ボーン一覧の基準バンドル",
        "Uses the input bundle or first selected file automatically. For batch folders, choose one representative bundle.":
            "入力バンドルまたは最初の選択ファイルを自動使用します。一括処理では基準バンドルを1つ選んでください。",
        "Bone transforms": "ボーン変形",
        "Select or type a bone, then add a transform. Scale is a multiplier; rotation is in degrees; movement uses bone-local units.":
            "ボーンを選択または入力して変形を追加します。スケールは倍率、回転は度、移動はボーンのローカル単位です。",
        "Select or type a bone": "ボーンを選択または入力",
        "Bone": "ボーン",
        "Load a bundle to see its bones, or type a bone name.": "バンドルからボーン一覧を読み込むか、名前を入力してください。",
        "Bones loaded. Select or type a name below.": "ボーンを読み込みました。下で名前を選択または入力してください。",
        "No skinned bones found in this bundle.": "このバンドルにはスキンボーンがありません。",
        "Load bones": "ボーンを読み込む",
        "Add transform": "変形を追加",
        "Remove": "削除",
        "Scale": "スケール",
        "Rotation (degrees)": "回転（度）",
        "Movement": "移動",
        "Compensate child scale": "子ボーンのスケールを補正",
        "Reset transform": "変形をリセット",
        "iOS/APK Selective Import": "iOS/APK 選択インポート",
        "Bundle Renamer (by texture)": "バンドル名変更（テクスチャ基準）",
        "Fix Bundle Export (world-space)": "バンドルエクスポート修正（ワールド空間）",
        "Edit SwingBone physics (stiffness / drag / rotation limits) on breast bones.": "胸ボーンのSwingBone物理（剛性 / 抵抗 / 回転制限）を編集します。",
        "Edit LiveCoreMemberNodeScaling.scaleValues on the BreastSize node.": "BreastSizeノードのLiveCoreMemberNodeScaling.scaleValuesを編集します。",
        "Scale skirt bone Transforms to lengthen or shorten skirts.": "スカートボーンのTransformをスケールして長短を調整します。",
        "Replace Texture2D images inside bundles from a folder of PNG/JPG files.": "PNG/JPGフォルダの画像でバンドル内のTexture2Dを置き換えます。",
        "Edit LiveCore scaling on the HipsSize node.": "HipsSizeノードのLiveCoreスケーリングを編集します。",
        "Repair LiveCoreMemberNodeScaling entries that don't match the bone's local transform.": "ボーンのローカルTransformと一致しないLiveCoreMemberNodeScaling項目を修復します。",
        "Edit SwingCollider radius/offset on upper-leg bones.": "太ももボーンのSwingCollider半径/オフセットを編集します。",
        "Package costume bundles into installer .zip packs (with thumbnail). Rina (209) needs BOTH the masked and no-mask bundles in one Batch run: they are detected and paired automatically by content. (If auto-pairing can't decide, name them '209rinamasked...' / '209rinaunmasked...' to pair explicitly.)":
            "衣装バンドルをインストーラー用.zipパック（サムネイル付き）にまとめます。璃奈（209）はバッチ1回でボード版・素顔版の両バンドルが必要です: 内容を解析して自動でペアリングし1つのパックにまとめます。（自動判別できない場合は「209rinamasked...」「209rinaunmasked...」の名前で明示的にペア指定できます。）",
        "Graft a donor costume's body mesh onto a target wearer model.": "提供元衣装のボディメッシュを対象の着用モデルに移植します。",
        "Bake bone scale/rotate/translate into mesh vertices.": "ボーンのスケール/回転/移動をメッシュ頂点にベイクします。",
        "Copy matching objects from a donor into a target by pathID (iOS/APK variant transfer).": "pathID基準で提供元の一致オブジェクトを対象にコピーします（iOS/APK間の移植）。",
        "Copy bundles into a folder, renamed by their ch####_co#### texture name (originals untouched).": "バンドルをch####_co####テクスチャ名に変更してフォルダにコピーします（原本はそのまま）。",
        "Normalize skinned meshes to world space for correct FBX export (in-game rendering unchanged).": "正しいFBXエクスポートのためスキンドメッシュをワールド空間に正規化します（ゲーム内描画は不変）。",
        "Character Body Info": "キャラ身体情報",
        "Reference: character ID, skin tone, breast size + jiggle tier, thigh type, and body scaling (Summer Splash 2020 costume; Mia/Lanzhu = Fest 3rd UR). Output appears in the log.":
            "参考用: キャラID、肌色、胸サイズ + jiggleティア、太ももタイプ、身体スケーリング（Summer Splash 2020 衣装; Mia/Lanzhu は Fest 3rd UR）。結果はログに表示されます。",
        "Character": "キャラ",
        "All characters": "全キャラ",
        "Accessory Un-clip": "アクセサリークリップ解除",
        "Skin Tone Changer": "肌色チェンジャー",
        "Costume Part Transplant": "衣装パーツ移植",
        "Lower Body Swap": "下半身スワップ",
        "Stop accessories transplanted onto a resized body from sinking in (lifts chest ornaments to match the bust).":
            "リサイズしたボディに移植したアクセサリーが埋もれるのを防ぎます（胸の装飾をバストに合わせて持ち上げ）。",
        "Recolour a body/hand texture image from one official skin-tone class to another (works on PNG images, not bundles).":
            "ボディ/ハンドのテクスチャ画像の肌色を公式トーンクラス間で変更します（バンドルではなくPNG画像が対象）。",
        "Move ONE costume part (wings / tail / cape) from a donor model onto a target wearer.":
            "衣装の1パーツ（羽/尻尾/マント）だけを提供元モデルから対象の着用者へ移します。",
        "Graft a good lower body from a donor onto a target that has deleted hip/thigh skin (the 'detached thighs' fix).":
            "下半身の肌が削除された対象に、提供元の正常な下半身を移植します（「太もも分離」修正）。",
        # Accessory Un-clip
        "Lift strength": "持ち上げ強度",
        "1.0 = match the bust exactly.": "1.0 = バストにぴったり合わせる。",
        "Min bust overlap": "最小バスト重なり",
        "Only lift parts overlapping the bust by at least this fraction.":
            "バストとこの割合以上重なるパーツのみ持ち上げます。",
        "Also pull in when shrunk": "縮小時も引き寄せる",
        "Force anchors (optional)": "アンカーを強制指定（任意）",
        "Comma-separated bone names to force; blank = auto-detect.":
            "強制するボーン名（カンマ区切り）; 空欄で自動検出。",
        # Skin Tone Changer
        "Input image": "入力画像",
        "A texture PNG/JPG (not a bundle).": "テクスチャPNG/JPG（バンドルではない）。",
        "From tone": "元のトーン",
        "To tone": "変換先トーン",
        "auto = detect from the image.": "auto = 画像から自動検出。",
        "Skin only (keep costume colours)": "肌のみ（衣装の色は保持）",
        "Strength (0–1)": "強さ (0–1)",
        # Costume Part Transplant
        "Donor bundle (has the part)": "提供元バンドル（パーツを持つ）",
        "Target bundle (wearer)": "対象バンドル（着用者）",
        "Part root bone (optional)": "パーツのルートボーン（任意）",
        "Part root bone": "パーツのルートボーン",
        "(auto — biggest part)": "(自動 — 最大パーツ)",
        "loading…": "読み込み中…",
        "Costume Recolour (irochi)": "衣装リカラー（色違い）",
        "Base costume model bundle": "ベース衣装モデルバンドル",
        "Colour-variant texture bundle (irochi)": "色変えテクスチャバンドル（色違い）",
        "Pick a part from the donor bundle (press Load to read its parts). Blank / auto = the biggest costume-specific part.":
            "提供元バンドルからパーツを選択（読み込みを押すとパーツ一覧を取得）。空欄/自動 = 最大の衣装固有パーツ。",
        "Named band presets, like the desktop tool. 'Custom' uses the Cut low/high Y + Region fields below. Y guide: ankle .11 · calf .30 · knee .50 · thigh .67 · crotch .85 · belly .92 · waist 1.05.":
            "デスクトップ版のような名前付きバンドプリセット。'Custom'は下の下部/上部Y + 領域フィールドを使用。Yガイド: 足首 .11 · ふくらはぎ .30 · 膝 .50 · 太もも .67 · 股 .85 · 下腹 .92 · 腰 1.05。",
        "Which bones may be replaced (used when Cut preset = Custom). 'lower' keeps the target's torso; 'lower_belly'/'central' reach up into the belly.":
            "置換できるボーン（Cutプリセット = Customのとき使用）。'lower'は対象の胴を維持し、'lower_belly'/'central'は下腹まで届く。",
        "Used when Cut preset = Custom. World-space Y of the lower cut; blank = floor. e.g. 0.50 = knee.":
            "Cutプリセット = Customのとき使用。下部カットのワールド空間Y; 空欄で床。例: 0.50 = 膝。",
        "Used when Cut preset = Custom. Blank = no upper limit. e.g. 0.96 = just below waist.":
            "Cutプリセット = Customのとき使用。空欄で上限なし。例: 0.96 = 腰のすぐ下。",
        "Keep only the donor's main body component (drops a thigh dagger, garter rings). Turn OFF if the donor's hips/thighs are a SEPARATE mesh piece and got left out (a cause of 'nothing to graft').":
            "提供元のメイン胴体コンポーネントのみ維持（太ももの短剣やガーターリングを除外）。提供元の尻/太ももが別メッシュで抜け落ちる場合はオフに（'移植対象なし'の原因）。",
        "Raise the cap's rim on every side (used together with the lift above).":
            "キャップの縁を全方向に持ち上げる（上のリフトと併用）。",
        "Report the drop/take triangle counts without writing — use to diagnose 'nothing to graft'.":
            "書き込まずに除去/取得する三角形数のみ報告 — '移植対象なし'の診断に使用。",
        "Apply a colour-variant (irochi) texture bundle onto its base costume model, so the model shows the alt colour (the _cN textures are a separate texture-only bundle in SIFAS).":
            "色変え（色違い）テクスチャバンドルをベース衣装モデルに適用し、モデルを別色で表示します（SIFASでは_cNテクスチャは別のテクスチャ専用バンドルです）。",
        "The full model bundle (has the mesh + base textures chXXXX_coYYYY_body/head).":
            "フルモデルバンドル（メッシュ + ベーステクスチャ chXXXX_coYYYY_body/head を含む）。",
        "The texture-only bundle with the _cN textures (chXXXX_coYYYY_body_c1 …). Must be the SAME costume as the base.":
            "_cNテクスチャを含むテクスチャ専用バンドル（chXXXX_coYYYY_body_c1 …）。ベースと同じ衣装である必要があります。",
        "Folder of decrypted bundles": "復号済みバンドルのフォルダ",
        "Auto-pairs every texture-only colour variant (_cN) with its complete model by the chXXXX_coYYYY code INSIDE the bundles and composites them all — no need to pick pairs. Just decrypt a costume pair (or a whole batch) into a folder and point here.":
            "各テクスチャ専用の色変え（_cN）を、バンドル内部の chXXXX_coYYYY コードで完成モデルと自動でペアリングし、すべて合成します — ペアを選ぶ必要なし。衣装ペア（または複数）をフォルダに復号して入れ、ここを指定してください。",
        "e.g. Wing_L_00; blank = auto-detect the biggest costume-specific part.":
            "例: Wing_L_00; 空欄で最大の衣装固有パーツを自動検出。",
        "Preserve part physics": "パーツの物理を保持",
        "Patch part texture onto target atlas": "パーツのテクスチャを対象アトラスにパッチ",
        # Lower Body Swap
        "Donor bundle (good lower body)": "提供元バンドル（正常な下半身）",
        "Target bundle (to fix)": "対象バンドル（修正対象）",
        "Region": "領域",
        "Cut low Y (optional)": "下部カットY（任意）",
        "World-space Y of the lower cut; blank = floor. e.g. 0.50 = knee.":
            "下部カットのワールド空間Y; 空欄で床。例: 0.50 = 膝。",
        "Cut high Y (optional)": "上部カットY（任意）",
        "Blank = no upper limit. e.g. 0.96 = just below waist.":
            "空欄で上限なし。例: 0.96 = 腰のすぐ下。",
        "Exclude donor accessories": "提供元のアクセサリーを除外",
        "Cut preset": "カットプリセット",
        "Fix detached thighs (hip/crotch) — recommended": "太もも分離を修正（尻/股） — 推奨",
        "Thigh & up (keep calf/shoes)": "太もも以上（ふくらはぎ/靴を維持）",
        "Calf part & up": "ふくらはぎ一部以上",
        "From calf & up (keep feet)": "ふくらはぎから上（足を維持）",
        "Whole lower body": "下半身全体",
        "Custom range (use Cut low/high Y below)": "カスタム範囲（下のY値を使用）",
        "Region (custom only)": "領域（カスタム時のみ）",
        "Cut low Y (custom)": "下部カットY（カスタム）",
        "Cut high Y (custom)": "上部カットY（カスタム）",
        "Cap edge lift — all sides": "キャップ縁リフト — 全側面",
        "Cap edge — front (blank = all)": "キャップ縁 — 前（空欄=全体）",
        "Cap edge — back (blank = all)": "キャップ縁 — 後（空欄=全体）",
        "Cap edge — left (blank = all)": "キャップ縁 — 左（空欄=全体）",
        "Cap edge — right (blank = all)": "キャップ縁 — 右（空欄=全体）",
        "Merge rim map too": "リムマップも統合",
        "Generate mipmaps": "ミップマップを生成",
        "Dry run (no write)": "ドライラン（書き込みなし）",
        # Breast physics parameter labels
        "stiffnessForce": "剛性 (stiffnessForce)",
        "dragForce": "抵抗 (dragForce)",
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
        "set scale": "スケール設定",
        "add Δ": "Δ加算",
        "set offset": "オフセット設定",
        "add offset Δ": "オフセットΔ加算",
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
        # costume transplant - desktop GUI parity (translations from costume_transplant.py)
        "Preserve appendage jiggle physics (collar / tie / wings)":
            "付属物のジグル物理を保持（襟 / タイ / 翼）",
        "Restore body collision for those bones": "該当ボーンのボディコリジョンを復元",
        "Only takes effect when appendage jiggle physics is preserved.":
            "付属物のジグル物理を保持が有効なときのみ適用されます。",
        "Realign body bones to the costume's rest pose (fixes offset ribbon/skirt)":
            "ボディボーンを衣装の基本ポーズに再整列（ずれたリボン/スカートを補正）",
        "World-space the body mesh (so swinging ribbon/skirt render correctly)":
            "ボディメッシュをワールド空間に（揺れるリボン/スカートが正しく描画されるよう）",
        "Re-anchor NodeScaling to realigned bones (keeps body shaping; stops the in-game ribbon dropping to the chest)":
            "再整列したボーンにNodeScalingを再アンカー（体型を維持; ゲーム内でリボンが胸に落ちるのを防止）",
        "Use the donor's swing physics for shared costume parts (skirt / ribbon) — the bust always stays the wearer's":
            "共有衣装パーツ（スカート / リボン）に提供元のスイング物理を使用 — バストは常に着用者のもの",
        "Special handling for masked / board-face models (Rina-chan board): auto-detect, protect head + body-shape scaling":
            "マスク / ボードフェイスモデル（りなちゃんボード）の特別処理: 自動検出、頭部 + 体型スケーリングを保護",
        "Transplant without the body textures (keep the wearer's own texture; only the costume mesh + bones are grafted)":
            "ボディテクスチャなしで移植（着用者のテクスチャを保持; 衣装メッシュ + ボーンのみ移植）",
        "Scale swing physics to a body-scaled target (keeps skirt/ribbon/wing/tail proportions on the Rina board; no-op on normal targets)":
            "ボディスケールされた対象にスイング物理をスケール（りなボードでスカート/リボン/翼/尻尾の比率を維持; 通常対象では無効）",
        "Match thigh to target character": "太ももを対象キャラに合わせる",
        "Scale the costume's thighs from the donor's body type to the target's (mesh baker).":
            "衣装の太ももを提供元の体型から対象の体型へスケールします（メッシュベイカー）。",
        "Match skin tone to target character": "肌色を対象キャラに合わせる",
        "Recolour the body skin from the donor's tone to the wearer's, so the transplanted costume shows the target character's skin (skin tone changer). On by default — turn it off to keep the donor's original skin. It covers the whole skin now; the shift lands on the target's official tone class (same as the standalone Skin Tone Changer).":
            "移植した衣装に対象キャラの肌が出るよう、ボディの肌を提供元のトーンから着用キャラのトーンへ再着色します（肌色チェンジャー）。既定でオン — オフにすると提供元の元の肌を保持します。今は肌全体をカバーし、変化量は対象の公式トーンクラスまで移動します（スタンドアロンのSkin Tone Changerと同じ）。",
        "Donor skin tone": "提供元の肌トーン",
        "auto = the donor character's official tone (pixel detection only when that is unknown). Set explicitly if the donor bundle was already recoloured.":
            "auto = 提供元キャラの公式トーン（不明な場合のみピクセルから検出）。提供元バンドルが既に再着色済みの場合は明示的に指定してください。",
        # --- desktop-parity options added to existing tools ---
        "Blank = leave unchanged. Desktop default 0.02 (the Soft feel).":
            "空欄で変更なし。デスクトップ既定値 0.02（Soft の感触）。",
        "Blank = leave unchanged. Desktop default 0.3 (the Soft feel).":
            "空欄で変更なし。デスクトップ既定値 0.3（Soft の感触）。",
        "Edit entries (advanced, single-file)": "エントリ編集（上級・単一ファイル）",
        "One per line, same grammar as the desktop --set: 'Bone;scaled=x,y,z;origin=x,y,z;kind=pos'. Edits existing entries. Ignored in batch (auto-repair only).":
            "1行に1つ、デスクトップの --set と同じ文法: 'Bone;scaled=x,y,z;origin=x,y,z;kind=pos'。既存エントリを編集。バッチでは無視（自動修復のみ）。",
        "Add entries (advanced, single-file)": "エントリ追加（上級・単一ファイル）",
        "One per line, same grammar as the desktop --add: 'Bone;scaled=x,y,z;kind=scale'. Adds a new entry for another bone (kind defaults to scale; origin defaults to the bone's current local).":
            "1行に1つ、デスクトップの --add と同じ文法: 'Bone;scaled=x,y,z;kind=scale'。別のボーンに新エントリを追加（kind 既定 scale、origin 既定はボーンの現在の local）。",
        "clamp radius min": "半径クランプ 最小",
        "Blank = no lower bound.": "空欄で下限なし。",
        "clamp radius max": "半径クランプ 最大",
        "Blank = no upper bound.": "空欄で上限なし。",
        "clamp offset min": "オフセットクランプ 最小",
        "Per-axis lower bound; blank = free.": "軸ごとの下限; 空欄で制限なし。",
        "clamp offset max": "オフセットクランプ 最大",
        "Per-axis upper bound; blank = free.": "軸ごとの上限; 空欄で制限なし。",
        "Spine compensation target": "スパイン補正の対象",
        "Which child bone absorbs the inverse scale for compensated Spine* targets. Only affects Spine* bakes.":
            "補正された Spine* ターゲットで逆スケールを吸収する子ボーン。Spine* のベイクのみに影響。",
        "Spine2 (widens Spine+Spine1)": "Spine2（Spine+Spine1 を広げる）",
        "Spine1": "Spine1",
        "Spine1 + Spine2": "Spine1 + Spine2",
        "Auto": "自動",
        "Include hidden meshes (foot_shadow · Hair · Face)": "非表示メッシュを含める（foot_shadow · Hair · Face）",
        "Only these meshes (advanced)": "これらのメッシュのみ（上級）",
        "Comma/newline separated mesh names; blank = all skinned, non-hidden meshes.":
            "カンマ/改行区切りのメッシュ名; 空欄で非表示以外の全スキンメッシュ。",
        "Objects whose m_Name matches are left as the target's (protects the wearer's face/head + shadows). Desktop default shown.":
            "m_Name が一致するオブジェクトは対象のものを維持（着用者の顔/頭 + 影を保護）。デスクトップ既定値を表示。",
        "Script class exclude (MonoBehaviour)": "スクリプトクラス除外（MonoBehaviour）",
        "Donor MonoBehaviours of these script classes are not copied, so the wearer keeps its own swing physics. Desktop default shown.":
            "これらのスクリプトクラスの提供元 MonoBehaviour はコピーせず、着用者が自身のスイング物理を維持します。デスクトップ既定値を表示。",
        "Digit-agnostic name matching": "数字を無視した名前マッチング",
        "Treat digits as wildcards, so ch0001_* matches any character id.":
            "数字をワイルドカードとして扱い、ch0001_* が任意のキャラ ID に一致。",
        "Name match mode": "名前マッチモード",
        "Remove original filename completely": "元のファイル名を完全に削除",
        "Name purely from the texture; collisions are auto-numbered so nothing is overwritten.":
            "テクスチャのみから命名; 衝突時は自動採番で上書きを防止。",
        "Add the part as its own sub-mesh + material (keep its texture)":
            "パーツを独自のサブメッシュ + マテリアルとして追加（テクスチャを保持）",
        "World-space the body mesh (so swinging parts render correctly)":
            "ボディメッシュをワールド空間に（揺れるパーツが正しく描画されるよう）",
        "Re-anchor NodeScaling (keep the wearer's body shaping)":
            "NodeScaling を再アンカー（着用者の体型を維持）",
        "Open skirt cap lift (0 = off)": "開いたスカートキャップのリフト（0 = オフ）",
        "Lift the open cap so a shorter donor lower body doesn't leave a hole; 0 = flat cap.":
            "短い提供元の下半身が穴を残さないように開いたキャップを持ち上げる; 0 = 平らなキャップ。",
        "Recolour skin only": "肌のみ再着色",
        "Restrict the recolour to the skin region, using the mesh's bone weights when available (excludes skirt / sleeves / ribbon / accessories) and never dropping real skin. NOTE: torso-tight clothing on body bones (a bodice) can't be told from chest skin, so its colour may still shift. For an exact result, export the texture and edit it with the Skin Tone Changer. On by default on the phone app, off on desktop.":
            "再着色を肌の領域に限定します。可能ならメッシュのボーンウェイトを使い（スカート/袖/リボン/アクセサリを除外）、実際の肌は決して取りこぼしません。注意: ボディボーンに密着した衣装（ボディス）は胸の肌と区別できず、色が変わることがあります。正確な結果が必要なら、テクスチャを export して肌色チェンジャーで直接編集してください。スマホアプリでは既定でオン、デスクトップではオフ。",
        "Also restrict by skin colour": "肌色でも制限",
        "Additionally require skin-like colour, so non-skin-coloured body-bone clothing (e.g. a blue bodice) is left alone. May drop deeply shadowed skin — leave off if any real skin gets missed.":
            "肌に近い色であることを追加条件にし、肌色でないボディボーンの衣装（例: 青いボディス）はそのまま残します。濃い影の肌は取りこぼす場合があるため、実際の肌が抜けるならオフにしてください。",
        "Target spec(s)": "対象スペック",
        "Target spec(s) — advanced": "対象スペック — 上級",
        "Thigh preset": "太ももプリセット",
        "Physics feel (preset)": "物理の感触（プリセット）",
        "Size preset (by character)": "サイズプリセット（キャラ別）",
        "Length preset": "長さプリセット",
        "One-click thigh resize: scales both UpLeg bones with child compensation.":
            "ワンクリック太ももリサイズ: 両方のUpLegボーンを子補正付きでスケールします。",
        "Optional manual bones, one per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1":
            "任意: 手動ボーン、1行に1つ: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1",
        "Fills stiffnessForce / dragForce below; you can still fine-tune.":
            "下のstiffnessForce / dragForceを埋めます。手動での微調整も可能です。",
        "Fills the X/Y/Z scale below with a character's in-game breast size.":
            "下のX/Y/Zスケールをキャラのゲーム内バストサイズで埋めます。",
        "Skirts usually scale uniformly; this fills X/Y/Z together.":
            "スカートは通常均一にスケールします。X/Y/Zをまとめて埋めます。",
        "(custom)": "(カスタム)",
        "Softer (0.01 / 0.2)": "より柔らかい (0.01 / 0.2)",
        "Soft (0.02 / 0.3)": "柔らかい (0.02 / 0.3)",
        "Firm (0.05 / 0.5)": "しっかり (0.05 / 0.5)",
        "Shorter (0.85)": "短く (0.85)",
        "Longer (1.15)": "長く (1.15)",
        "Reset (1.0)": "リセット (1.0)",
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
        "A single UnityFS asset bundle.": "単一のUnityFSアセットバンドル。",
        "All bundles under here are processed.": "このフォルダ配下のすべてのバンドルが処理されます。",
        "Where modified bundles are written.": "変更後のバンドルの保存先。",
        "Comma/space separated SwingBone GameObject name patterns.": "カンマ/空白区切りのSwingBone GameObject名パターン。",
        "Blank = leave unchanged.": "空欄なら変更しません。",
        "Detect the character and tag the output with its jiggleN tier.": "キャラを検出し、出力にjiggleNティアを付与します。",
        "Auto jiggle": "自動jiggle",
        "Off": "オフ",
        "Match current breast size": "現在の胸サイズに合わせる",
        "Follow character (stock)": "キャラの標準に従う",
        "Match current breast size = follow the size already in the bundle (best after resizing). Follow character = the character's stock tier.":
            "現在の胸サイズに合わせる = バンドルに既に適用されたサイズに従います（リサイズ後に推奨）。キャラの標準 = キャラの標準tier。",
        "Defaults to the installer's suit/ drop folder, so Install Costume picks the pack up right away.":
            "インストーラーのsuit/ドロップフォルダが既定なので、Install Costumeがすぐにパックを認識します。",
        "Absolute scale; blank to skip this axis.": "絶対スケール。空欄ならこの軸をスキップ。",
        "Absolute scale; blank to skip. Uniform 0.85 = shorter, 1.15 = longer.": "絶対スケール。空欄ならスキップ。均一0.85=短く、1.15=長く。",
        "Replacement images named after the texture (e.g. ch0107_co0001_body.png).": "テクスチャ名と同名の置換画像（例: ch0107_co0001_body.png）。",
        "In the phone app pick RGBA32 (uncompressed) or an ASTC format (what SIFAS uses — encoded on-device). ETC/DXT/BC and Keep Original need the desktop tools.":
            "スマホアプリではRGBA32（非圧縮 — 端末で動作）を選んでください。圧縮形式（ASTC/ETC/DXT）とKeep Originalはデスクトップ版が必要です。",
        "rebase = re-anchor to current local; neutralize = reset; none = scan only.": "rebase=現在のローカルに再アンカー、neutralize=リセット、none=スキャンのみ。",
        "Used when auto-detect is off or fails.": "自動検出がオフ、または失敗した場合に使用します。",
        "One per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1": "1行に1つ: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1",
        "e.g. slim:thick (optional; slim/default/thick).": "例: slim:thick（任意; slim/default/thick）。",
        "Folder of bundles to rename.": "名前を変更するバンドルのフォルダ。",
        "Renamed copies go here.": "名前変更後のコピーの保存先。",
        "Blank = no limit.": "空欄なら制限なし。",
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
        "LiveCoreMemberNodeScaling scaler (HipsSize)": "LiveCoreMemberNodeScaling スケーラー (HipsSize)",
        "Target GameObject name": "対象GameObject名",
        "Set scaledValue (x,y,z)": "scaledValue設定 (x,y,z)",
        "Add Δ (dx,dy,dz)": "Δ加算 (dx,dy,dz)",
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
        "Skirt GO name patterns (comma/space, contains match)": "スカートGameObject名パターン（カンマ/空白、部分一致）",
        "Uniform scale  (x = y = z - the usual skirt change)": "均一スケール（x = y = z - 通常のスカート変更）",
        "factor:": "倍率:",
        "Apply": "適用",
        "Shorter 0.85": "短く 0.85",
        "Longer 1.15": "長く 1.15",
        "Reset 1.0": "リセット 1.0",
        "Advanced - per-axis set (x, y, z)  -  blank = leave that axis": "詳細 - 軸ごとに設定 (x, y, z) - 空欄ならその軸は維持",
        "Advanced - add delta (dx, dy, dz)  -  added to current value": "詳細 - デルタ加算 (dx, dy, dz) - 現在値に加算",
        "Skirt length/volume usually scales uniformly, so x, y, z move together. Use the factor above; the per-axis fields are for fine cases.": "スカートの丈/ボリュームは通常均一にスケールし、x, y, z は一緒に動きます。上の倍率を使ってください。軸ごとのフィールドは細かい調整用です。",
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
        "Language changed. Restart the tool to apply it.": "言語を変更しました。適用するにはツールを再起動してください。"
    },
}


# Shared 3D viewer labels; English remains the source and fallback.
_VIEWER_TRANSLATIONS = {
    "3D model": [
        "3D 모델",
        "3Dモデル"
    ],
    "Choose a costume model. Add a separate head or hair file if it is missing.": [
        "의상 모델을 선택하세요. 머리나 헤어가 따로 있는 의상은 해당 파일도 추가하세요.",
        "衣装モデルを選んでください。頭や髪が別ファイルの場合は、そのファイルも追加してください。"
    ],
    "Choose costume file": [
        "의상 파일 선택",
        "衣装ファイルを選択"
    ],
    "Open model": [
        "모델 열기",
        "モデルを開く"
    ],
    "Choose a costume file to begin.": [
        "의상 파일을 선택해 시작하세요.",
        "衣装ファイルを選んでください。"
    ],
    "Your model will appear here.": [
        "선택한 모델이 여기에 표시됩니다.",
        "選んだモデルがここに表示されます。"
    ],
    "Preparing model…": [
        "모델을 준비하는 중…",
        "モデルを準備中…"
    ],
    "Front": [
        "정면",
        "正面"
    ],
    "Back": [
        "뒤",
        "背面"
    ],
    "Left side": [
        "왼쪽",
        "左側"
    ],
    "Right side": [
        "오른쪽",
        "右側"
    ],
    "Fit model": [
        "전체 보기",
        "全体を表示"
    ],
    "Drag to rotate · Pinch or scroll to zoom · Two fingers to move": [
        "드래그로 회전 · 두 손가락이나 스크롤로 확대 · 두 손가락으로 이동",
        "ドラッグで回転 · ピンチやスクロールで拡大 · 2本指で移動"
    ],
    "Display options": [
        "보기 설정",
        "表示設定"
    ],
    "Show textures": [
        "텍스처 표시",
        "テクスチャを表示"
    ],
    "Wireframe": [
        "메시 선 표시",
        "ワイヤーフレーム"
    ],
    "Background": [
        "배경",
        "背景"
    ],
    "Light": [
        "밝게",
        "明るい"
    ],
    "Dark": [
        "어둡게",
        "暗い"
    ],
    "Perspective": [
        "원근감",
        "遠近感"
    ],
    "This is a static model preview. Game lighting and motion may look different.": [
        "정지 상태의 모델 미리보기입니다. 게임의 조명이나 움직임에 따라 다르게 보일 수 있습니다.",
        "静止したモデルのプレビューです。ゲーム内の照明や動作により見え方が変わります。"
    ],
    "Visible parts": [
        "표시할 파츠",
        "表示するパーツ"
    ],
    "Expand view": [
        "화면 크게",
        "大きく表示"
    ],
    "Close expanded view": [
        "크게 보기 닫기",
        "拡大表示を閉じる"
    ],
    "Meshes: {meshes} · Triangles: {triangles}": [
        "메시 {meshes}개 · 삼각형 {triangles}개",
        "メッシュ {meshes}個 · 三角形 {triangles}個"
    ],
    "Model ready.": [
        "모델을 불러왔습니다.",
        "モデルを読み込みました。"
    ],
    "Files changed. Press Open model to refresh the preview.": [
        "파일 선택이 바뀌었습니다. 모델 열기를 눌러 미리보기를 갱신하세요.",
        "ファイルの選択が変わりました。モデルを開くを押して表示を更新してください。"
    ],
    "Press Open model to see the costume.": [
        "모델 열기를 누르면 의상이 표시됩니다.",
        "モデルを開くを押すと衣装が表示されます。"
    ],
    "Loading cancelled.": [
        "불러오기를 취소했습니다.",
        "読み込みを取り消しました。"
    ],
    "The 3D viewer files could not be loaded. Reopen the app and try again.": [
        "3D 뷰어 파일을 불러오지 못했습니다. 앱을 다시 열어주세요.",
        "3Dビューアを読み込めませんでした。アプリを開き直してください。"
    ],
    "3D graphics were interrupted. Wait a moment, then open the model again.": [
        "3D 표시가 중단되었습니다. 잠시 후 모델을 다시 열어주세요.",
        "3D表示が中断されました。少し待ってからモデルを開き直してください。"
    ],
    "3D graphics are unavailable here. Update Android System WebView or use a current browser.": [
        "3D 그래픽을 사용할 수 없습니다. Android System WebView를 업데이트하거나 최신 브라우저로 열어주세요.",
        "3D表示を利用できません。Android System WebViewを更新するか、新しいブラウザで開いてください。"
    ],
    "Part": [
        "파츠",
        "パーツ"
    ],
    "The costume file could not be opened.": [
        "의상 파일을 열지 못했습니다.",
        "衣装ファイルを開けませんでした。"
    ],
    "The model could not be displayed. Try another costume file.": [
        "모델을 표시하지 못했습니다. 다른 의상 파일로 시도해보세요.",
        "モデルを表示できませんでした。別の衣装ファイルを試してください。"
    ],
    "Loading 3D model…": [
        "3D 모델을 불러오는 중…",
        "3Dモデルを読み込み中…"
    ],
    "The preview expired. Open the model again.": [
        "미리보기 보관 시간이 지났습니다. 모델을 다시 열어주세요.",
        "プレビューの保存期限が切れました。モデルを開き直してください。"
    ],
    "This model is too large to preview on this device.": [
        "이 기기에서 미리보기에는 너무 큰 모델입니다.",
        "この端末でプレビューするにはモデルが大きすぎます。"
    ],
    "No visible model was found in these files.": [
        "선택한 파일에서 표시할 모델을 찾지 못했습니다.",
        "選んだファイルに表示できるモデルが見つかりませんでした。"
    ],
    "The model could not be displayed.": [
        "모델을 표시하지 못했습니다.",
        "モデルを表示できませんでした。"
    ],
    "Choose up to eight costume files at a time.": [
        "의상 파일은 한 번에 8개까지 선택할 수 있습니다.",
        "衣装ファイルは一度に8個まで選べます。"
    ],
    "View input model": [
        "입력 모델 보기",
        "入力モデルを見る"
    ],
    "View saved model": [
        "저장 모델 보기",
        "保存モデルを見る"
    ],
    "View in 3D": [
        "3D로 보기",
        "3Dで見る"
    ],
    "Clothing attached to a body part can change with it. Save a new model, then choose View saved model to check the result in 3D.": [
        "해당 부위에 붙어 있는 의상도 함께 변할 수 있습니다. 모델을 저장한 뒤 저장 모델 보기를 눌러 3D로 결과를 확인하세요.",
        "部位に付いた衣装も一緒に変形する場合があります。モデルを保存し、保存モデルを見るから3Dで結果を確認してください。"
    ],
    "View representative textures here, or open the costume in 3D model to inspect its shape.": [
        "여기서는 대표 텍스처를 확인할 수 있습니다. 형태를 보려면 의상을 3D 모델로 열어보세요.",
        "ここでは代表テクスチャを確認できます。形を見るには衣装を3Dモデルで開いてください。"
    ],
    "Some parts have no preview texture and use a neutral color.": [
        "미리보기 텍스처가 없는 파츠는 기본 색상으로 표시됩니다.",
        "プレビュー用テクスチャがないパーツは標準色で表示されます。"
    ]
}
_VIEWER_TRANSLATIONS.update({
    "Some textures could not be displayed. A neutral surface is shown instead.": [
        "일부 텍스처를 표시하지 못해 해당 파츠를 기본 색상으로 표시합니다.",
        "一部のテクスチャを表示できないため、標準色で表示しています。"
    ],
    "A linked texture is missing. Add its companion model file to the preview.": [
        "연결된 텍스처가 없습니다. 해당 텍스처가 들어 있는 모델 파일도 추가해주세요.",
        "参照先のテクスチャがありません。対応するモデルファイルも追加してください。"
    ],
    "A linked mesh is missing. Add its companion model file to the preview.": [
        "연결된 파츠가 없습니다. 해당 파츠가 들어 있는 모델 파일도 추가해주세요.",
        "参照先のパーツがありません。対応するモデルファイルも追加してください。"
    ],
    "This costume needs its separate facial asset to show eyes and expressions.": [
        "얼굴 파일을 함께 열면 눈과 표정까지 볼 수 있습니다.",
        "顔のファイルも一緒に開くと、目や表情を表示できます。"
    ],
    "Another model is opening. Wait for it to finish and try again.": [
        "다른 모델을 여는 중입니다. 완료된 후 다시 시도해주세요.",
        "別のモデルを開いています。完了後にもう一度試してください。"
    ],
    "This model could not be opened. Its format or linked assets may be unsupported.": [
        "이 모델을 열지 못했습니다. 지원하지 않는 형식이거나 함께 필요한 파일이 빠졌을 수 있습니다.",
        "このモデルを開けませんでした。非対応の形式か、必要な関連ファイルが不足している可能性があります。"
    ],
    "Model preview took too long. Try opening fewer model files.": [
        "모델을 여는 데 시간이 너무 오래 걸렸습니다. 파일 수를 줄여 다시 시도해주세요.",
        "モデルの読み込みに時間がかかりすぎました。ファイル数を減らして試してください。"
    ],
    "Choose between one and eight extracted Unity model files.": [
        "추출된 의상 모델 파일을 1~8개 선택해주세요.",
        "抽出済みの衣装モデルファイルを1～8個選んでください。"
    ],
    "Choose an extracted Unity model file.": [
        "추출된 의상 모델 파일을 선택해주세요.",
        "抽出済みの衣装モデルファイルを選んでください。"
    ],
    "A selected model file no longer exists.": [
        "선택한 모델 파일을 찾을 수 없습니다. 다시 선택해주세요.",
        "選んだモデルファイルが見つかりません。選び直してください。"
    ],
    "A model file is too large for the mobile viewer.": [
        "이 모델 파일은 기기에서 열기에 너무 큽니다.",
        "このモデルファイルは端末で開くには大きすぎます。"
    ],
    "The selected model files are too large. Open fewer files.": [
        "선택한 모델 파일의 용량이 너무 큽니다. 파일 수를 줄여주세요.",
        "選んだモデルファイルの容量が大きすぎます。ファイル数を減らしてください。"
    ]
})
_VIEWER_TRANSLATIONS.update({
    "Open a costume model or ZIP. Missing facial parts can be added automatically.": [
        "의상 모델이나 ZIP을 여세요. 빠진 얼굴 파츠는 자동으로 불러올 수 있습니다.",
        "衣装モデルやZIPを開いてください。足りない顔パーツを自動で追加できます。"
    ],
    "Choose costume model or ZIP": [
        "의상 모델 또는 ZIP 선택",
        "衣装モデルまたはZIPを選択"
    ],
    "Complete face automatically": [
        "얼굴 자동 완성",
        "顔を自動で補う"
    ],
    "Uses the character's original face for missing parts.": [
        "빠진 얼굴 파츠만 캐릭터의 원본으로 채웁니다.",
        "足りない顔パーツだけ元のデータから補います。"
    ],
    "Checking model and face…": [
        "의상과 얼굴을 확인하는 중…",
        "衣装と顔を確認中…"
    ],
    "Face option changed. Press Open model to refresh the preview.": [
        "얼굴 설정이 바뀌었습니다. 모델 열기를 눌러 갱신하세요.",
        "顔の設定が変わりました。モデルを開くを押して更新してください。"
    ],
    "Missing face parts were added automatically.": [
        "빠진 얼굴 파츠를 원본에서 자동으로 채웠습니다.",
        "足りない顔パーツを元のデータから自動で補いました。"
    ],
    "The model already includes its face.": [
        "의상에 포함된 얼굴을 그대로 표시합니다.",
        "衣装に含まれる顔をそのまま表示しています。"
    ],
    "Some face parts were added; other parts are still missing.": [
        "얼굴 파츠 일부를 채웠지만 아직 빠진 파츠가 있습니다.",
        "顔パーツの一部を追加しましたが、まだ不足しているパーツがあります。"
    ],
    "The original face could not be added. The available costume parts are shown.": [
        "원본 얼굴을 불러오지 못해 현재 파일에 있는 파츠만 표시합니다.",
        "元の顔を追加できなかったため、現在のファイルにあるパーツを表示しています。"
    ]
})
_VIEWER_TRANSLATIONS.update({
    "The model's character could not be identified safely, so an original face was not added.": [
        "모델의 캐릭터를 정확히 확인할 수 없어 원본 얼굴을 추가하지 않았습니다.",
        "モデルのキャラクターを確実に識別できないため、元の顔を追加しませんでした。"
    ],
    "The mod's character metadata disagrees with its Unity model. The Unity model's owner is used.": [
        "모드 설명과 모델의 캐릭터 정보가 다릅니다. 모델에 기록된 캐릭터를 기준으로 표시합니다.",
        "MODの説明とモデルのキャラクター情報が異なります。モデルに記録されたキャラクターを使用します。"
    ],
    "The original face could not be obtained. The costume is still shown; keep a same-character original model locally or check the asset CDN connection.": [
        "원본 얼굴을 불러오지 못했습니다. 의상은 표시됩니다. 같은 캐릭터의 원본 모델을 기기에 보관하거나 리소스 서버 연결을 확인해주세요.",
        "元の顔を取得できませんでした。衣装は表示されます。同じキャラクターの元モデルを端末に用意するか、リソース配信サーバーへの接続を確認してください。"
    ],
    "The original face could not be opened. The costume is still shown.": [
        "원본 얼굴을 열지 못했습니다. 불러온 의상은 계속 확인할 수 있습니다.",
        "元の顔を開けませんでした。読み込んだ衣装は引き続き確認できます。"
    ]
})
_VIEWER_TRANSLATIONS.update({
    "Some bone transforms are unavailable. Those parts use their saved renderer placement.": [
        "일부 파츠의 본 정보를 찾지 못해 저장된 위치로 표시합니다.",
        "一部のボーン情報が見つからないため、該当パーツを保存済みの配置で表示します。"
    ],
    "Some vertices have no bone weights and use their saved renderer placement.": [
        "일부 정점에 본 연결 정보가 없어 저장된 위치로 표시합니다.",
        "一部の頂点にボーンのウェイト情報がないため、保存済みの配置で表示します。"
    ]
})
_VIEWER_TRANSLATIONS.update({
    "Fills missing face parts from the originals. Uses the internet if needed.": [
        "빠진 얼굴 파츠만 원본으로 채웁니다. 필요하면 인터넷에서 불러옵니다.",
        "不足した顔パーツだけ元データで補います。必要に応じて通信します。"
    ]
})
for _source, _translated in _VIEWER_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _translated[0]
    _TABLES["ja"][_source] = _translated[1]
