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
        "Asset editing tools": "에셋 편집툴",
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
        "Reuse empty UV areas": "빈 UV 영역 재사용",
        "Try the donor's original UV position first. If occupied, use an atlas or enable moving to another empty UV area. No padding is added.":
            "Donor의 원래 UV 위치를 먼저 사용합니다. 겹치면 아틀라스로 합치거나 다른 빈 UV 영역으로 옮기기를 켜세요. 패딩은 추가하지 않습니다.",
        "Move to another empty UV area": "다른 빈 UV 영역으로 옮기기",
        "Match smaller textures to larger ones": "작은 이미지를 큰 이미지에 맞추기",
        "Texture and UV placement": "텍스처·UV 배치 방식",
        "Head meshes cannot use a new texture atlas. The game draws every head mesh with the original head material, so an atlas would never be shown and would move the blush. Choose Body as the receiving mesh, or use original or empty UV positions.":
            "머리 메시에는 새 텍스처 아틀라스를 사용할 수 없습니다. 게임은 머리 아래의 모든 메시를 원래 머리 머티리얼로 그리므로 아틀라스는 표시되지 않고 홍조 위치도 틀어집니다. 이식받을 메시로 Body를 고르거나, 원래 UV 위치 또는 빈 UV 영역을 사용하세요.",
        "Load the costume together with its face before transplanting onto a head mesh. The game draws the face's eyes and mouth from the same head texture, and their areas must be protected.":
            "머리 메시에 이식하려면 의상을 얼굴과 함께 불러오세요. 게임은 얼굴의 눈과 입도 같은 머리 텍스처로 그리므로 그 영역을 보호해야 합니다.",
        "The head texture has no free area for the selected part outside the face, eyes, mouth, blush and existing head meshes. Choose Body as the receiving mesh, or select a smaller part.":
            "머리 텍스처에 얼굴·눈·입·홍조와 기존 머리 메시를 피해 선택한 부분을 넣을 빈 곳이 없습니다. 이식받을 메시로 Body를 고르거나 더 작은 부분을 선택하세요.",
        "The face mesh cannot receive a part. The game rebuilds it into its combined face with the original head material and fixed blush positions. Choose Body or Hair as the receiving mesh.":
            "얼굴 메시에는 부분을 이식할 수 없습니다. 게임은 얼굴 메시를 원래 머리 머티리얼과 고정된 홍조 위치로 다시 합쳐 그립니다. 이식받을 메시로 Body나 Hair를 고르세요.",
        "One game material holds one culling setting, so the donor's and the receiving mesh's materials must match. Choose a receiving mesh whose material uses the same culling, such as Body or Hair.":
            "게임 머티리얼 하나에는 컬링 설정이 하나뿐이므로 도너 머티리얼과 이식받을 메시의 머티리얼이 같아야 합니다. 같은 컬링을 쓰는 머티리얼의 메시(Body나 Hair 등)를 이식받을 메시로 고르세요.",
        "A texture of the selected part has finer pixels for its UV area than the matching head texture. The head's textures keep their size, because the face, eyes and mouth are drawn from them. Choose Body as the receiving mesh.":
            "선택한 부분의 텍스처가 같은 UV 면적에 대해 대응하는 머리 텍스처보다 더 촘촘한 픽셀을 씁니다. 얼굴·눈·입이 머리 텍스처로 그려지므로 머리 텍스처의 크기는 바꾸지 않습니다. 이식받을 메시로 Body를 고르세요.",
        "The selected part's original UV position in the head texture is already used by the face, eyes, mouth, blush or another head mesh. Choose 'Move into empty UV areas', or Body as the receiving mesh.":
            "선택한 부분의 원래 UV 위치는 머리 텍스처에서 이미 얼굴·눈·입·홍조 또는 다른 머리 메시가 쓰고 있습니다. '빈 UV 영역으로 이동'을 고르거나, 이식받을 메시로 Body를 고르세요.",
        "The selected part's textures cannot be written into the head texture with their exact pixels; the log names the reason. Choose Body as the receiving mesh.":
            "선택한 부분의 텍스처를 원래 픽셀 그대로 머리 텍스처에 넣을 수 없습니다. 이유는 로그에 있습니다. 이식받을 메시로 Body를 고르세요.",
        "The head's BodyPartManager.headMaterial must be stored in the costume before grafting onto a head mesh.":
            "머리 메시에 이식하려면 머리의 BodyPartManager.headMaterial이 의상 파일 안에 저장되어 있어야 합니다.",
        "A head-texture mesh stores its vertices outside the bundle; reopen the original costume and face.":
            "머리 텍스처를 쓰는 메시의 정점 데이터가 번들 밖에 저장되어 있습니다. 원래 의상과 얼굴을 다시 여세요.",
        "A head-texture mesh is compressed; its texture area cannot be protected.":
            "머리 텍스처를 쓰는 메시가 압축되어 있어 그 텍스처 영역을 보호할 수 없습니다.",
        "A head-texture mesh has triangles without UV0 coordinates.":
            "머리 텍스처를 쓰는 메시에 UV0 좌표가 없는 삼각형이 있습니다.",
        "A head-texture mesh has invalid UV0 coordinates.":
            "머리 텍스처를 쓰는 메시의 UV0 좌표가 올바르지 않습니다.",
        "A head-texture mesh references an invalid vertex.":
            "머리 텍스처를 쓰는 메시가 잘못된 정점을 참조합니다.",
        "A head-texture surface references a mesh outside its bundle; its texture area cannot be protected.":
            "머리 텍스처를 쓰는 표면이 번들 밖의 메시를 참조하므로 그 텍스처 영역을 보호할 수 없습니다.",
        "Receiving mesh":
            "이식받을 메시",
        "Body and other meshes outside the head: the part keeps following its own bones, so a head accessory stays on the head. Its texture goes into that mesh's own texture, where an atlas is allowed, and the blush is not affected. Body and head meshes draw in the same order with the same outline.":
            "Body 등 머리 밖의 메시: 이식한 부분은 원래 본을 그대로 따라가므로 머리 장식은 계속 머리에 붙어 있습니다. 텍스처는 그 메시의 텍스처에 들어가며 아틀라스도 사용할 수 있고, 홍조에는 영향이 없습니다. Body와 머리 메시는 같은 순서와 같은 외곽선으로 그려집니다.",
        "Meshes under the head (such as Hair): the game draws every head mesh with the shared head material. The part's texture must fit in free head-texture space outside the face, eyes, mouth and blush; no atlas is made, and the face must be loaded. Body and head meshes draw in the same order with the same outline.":
            "머리 아래 메시(Hair 등): 게임은 머리 아래의 모든 메시를 공용 머리 머티리얼로 그립니다. 이식한 부분의 텍스처는 얼굴·눈·입·홍조 영역을 피해 머리 텍스처의 빈 곳에 들어가야 하며, 아틀라스는 만들지 않고 얼굴도 함께 불러와야 합니다. Body와 머리 메시는 같은 순서와 같은 외곽선으로 그려집니다.",
        "Reuse original UV positions": "원래 UV 위치 재사용",
        "Match corresponding main, rimlight and other UV textures to the larger resolution and keep the original UV positions. If those positions are occupied, use a new atlas. Head meshes are never combined into an atlas. No padding is added.": "메인·림라이트 등 대응 이미지를 각각 큰 쪽 해상도로 맞추고 원래 UV 위치를 유지합니다. 원래 위치가 사용 중이면 새 아틀라스로 합칩니다. 머리 메시는 아틀라스로 합치지 않습니다. 패딩은 추가하지 않습니다.",
        "Move into empty UV areas": "빈 UV 영역으로 이동",
        "Keep main-texture resolution, match auxiliary-map ratios, and move each selected UV island with its textures into unused space. If no space fits, use a new atlas. Head meshes are never combined into an atlas. No padding is added.": "메인 텍스처 해상도는 유지하고 보조 맵의 비율을 맞춘 뒤, 선택한 UV 섬마다 텍스처와 함께 빈 공간으로 옮깁니다. 들어갈 공간이 없으면 새 아틀라스로 합칩니다. 머리 메시는 아틀라스로 합치지 않습니다. 패딩은 추가하지 않습니다.",
        "Build a new texture atlas": "새 아틀라스로 합치기",
        "Combine textures into a new atlas and remap UVs. Not available for head meshes. No padding is added.": "텍스처를 새 아틀라스로 합치고 UV를 다시 배치합니다. 머리 메시에는 사용할 수 없습니다. 패딩은 추가하지 않습니다.",
        "Before either UV reuse method, enlarge corresponding main, rimlight and other UV textures to the larger resolution. No padding is added.":
            "두 UV 재사용 방식에 앞서 메인·림라이트 등 대응하는 UV 텍스처를 큰 쪽 해상도로 확대합니다. 패딩은 추가하지 않습니다.",
        "If the original UV position is occupied, find another empty area without reducing source pixel detail. No padding is added.":
            "원래 UV 위치가 사용 중이면 원본 픽셀의 세부 표현을 유지한 채 다른 빈 영역을 찾습니다. 패딩은 추가하지 않습니다.",
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
        "Lift the open cap to close gaps above a shorter lower body. Open caps require a new texture atlas. Use 0 for a flat cap.":
            "짧은 하체 위의 틈을 메우려면 열린 캡을 들어 올리세요. 열린 캡에는 새 텍스처 아틀라스가 필요합니다. 평평한 캡은 0으로 설정하세요.",
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
        "Asset editing tools": "アセット編集ツール",
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
        "Reuse empty UV areas": "空きUV領域を再利用",
        "Try the donor's original UV position first. If occupied, use an atlas or enable moving to another empty UV area. No padding is added.":
            "ドナーの元のUV位置を優先します。重なる場合はアトラスに結合するか、別の空きUV領域への移動を有効にしてください。パディングは追加しません。",
        "Move to another empty UV area": "別の空きUV領域へ移動",
        "Match smaller textures to larger ones": "小さい画像を大きい画像に合わせる",
        "Texture and UV placement": "テクスチャ・UVの配置方法",
        "Head meshes cannot use a new texture atlas. The game draws every head mesh with the original head material, so an atlas would never be shown and would move the blush. Choose Body as the receiving mesh, or use original or empty UV positions.":
            "頭のメッシュには新しいテクスチャアトラスを使えません。ゲームは頭の下のすべてのメッシュを元の頭マテリアルで描画するため、アトラスは表示されず、チークの位置もずれます。移植先のメッシュにBodyを選ぶか、元のUV位置または空きUV領域を使ってください。",
        "Load the costume together with its face before transplanting onto a head mesh. The game draws the face's eyes and mouth from the same head texture, and their areas must be protected.":
            "頭のメッシュに移植するには、衣装を顔と一緒に読み込んでください。ゲームは顔の目と口も同じ頭テクスチャで描画するため、その領域を保護する必要があります。",
        "The head texture has no free area for the selected part outside the face, eyes, mouth, blush and existing head meshes. Choose Body as the receiving mesh, or select a smaller part.":
            "頭テクスチャに、顔・目・口・チークと既存の頭メッシュを避けて選択パーツを入れる空きがありません。移植先のメッシュにBodyを選ぶか、より小さいパーツを選択してください。",
        "The face mesh cannot receive a part. The game rebuilds it into its combined face with the original head material and fixed blush positions. Choose Body or Hair as the receiving mesh.":
            "顔のメッシュにはパーツを移植できません。ゲームは顔のメッシュを元の頭マテリアルと固定のチーク位置で結合し直して描画します。移植先のメッシュにBodyかHairを選んでください。",
        "One game material holds one culling setting, so the donor's and the receiving mesh's materials must match. Choose a receiving mesh whose material uses the same culling, such as Body or Hair.":
            "ゲームのマテリアル1つにはカリング設定が1つしかないため、ドナーと移植先のメッシュのマテリアルが一致する必要があります。同じカリングを使うマテリアルのメッシュ（BodyやHairなど）を移植先に選んでください。",
        "A texture of the selected part has finer pixels for its UV area than the matching head texture. The head's textures keep their size, because the face, eyes and mouth are drawn from them. Choose Body as the receiving mesh.":
            "選択したパーツのテクスチャは、同じUV面積に対して対応する頭テクスチャより細かいピクセルを使っています。顔・目・口は頭テクスチャで描画されるため、頭テクスチャのサイズは変更しません。移植先のメッシュにBodyを選んでください。",
        "The selected part's original UV position in the head texture is already used by the face, eyes, mouth, blush or another head mesh. Choose 'Move into empty UV areas', or Body as the receiving mesh.":
            "選択したパーツの元のUV位置は、頭テクスチャ上ですでに顔・目・口・チークまたは別の頭メッシュが使っています。「空きUV領域へ移動」を選ぶか、移植先のメッシュにBodyを選んでください。",
        "The selected part's textures cannot be written into the head texture with their exact pixels; the log names the reason. Choose Body as the receiving mesh.":
            "選択したパーツのテクスチャを元のピクセルのまま頭テクスチャに書き込めません。理由はログに記録されています。移植先のメッシュにBodyを選んでください。",
        "The head's BodyPartManager.headMaterial must be stored in the costume before grafting onto a head mesh.":
            "頭のメッシュに移植するには、頭のBodyPartManager.headMaterialが衣装ファイル内に保存されている必要があります。",
        "A head-texture mesh stores its vertices outside the bundle; reopen the original costume and face.":
            "頭テクスチャを使うメッシュの頂点データがバンドルの外に保存されています。元の衣装と顔を開き直してください。",
        "A head-texture mesh is compressed; its texture area cannot be protected.":
            "頭テクスチャを使うメッシュが圧縮されているため、そのテクスチャ領域を保護できません。",
        "A head-texture mesh has triangles without UV0 coordinates.":
            "頭テクスチャを使うメッシュに、UV0座標のない三角形があります。",
        "A head-texture mesh has invalid UV0 coordinates.":
            "頭テクスチャを使うメッシュのUV0座標が不正です。",
        "A head-texture mesh references an invalid vertex.":
            "頭テクスチャを使うメッシュが無効な頂点を参照しています。",
        "A head-texture surface references a mesh outside its bundle; its texture area cannot be protected.":
            "頭テクスチャを使う面がバンドル外のメッシュを参照しているため、そのテクスチャ領域を保護できません。",
        "Receiving mesh":
            "移植先のメッシュ",
        "Body and other meshes outside the head: the part keeps following its own bones, so a head accessory stays on the head. Its texture goes into that mesh's own texture, where an atlas is allowed, and the blush is not affected. Body and head meshes draw in the same order with the same outline.":
            "Bodyなど頭の外のメッシュ：移植したパーツは元のボーンに従うため、頭のアクセサリーは頭に付いたままです。テクスチャはそのメッシュのテクスチャに入り、アトラスも使えます。チークには影響しません。Bodyと頭のメッシュは同じ順序・同じアウトラインで描画されます。",
        "Meshes under the head (such as Hair): the game draws every head mesh with the shared head material. The part's texture must fit in free head-texture space outside the face, eyes, mouth and blush; no atlas is made, and the face must be loaded. Body and head meshes draw in the same order with the same outline.":
            "頭の下のメッシュ（Hairなど）：ゲームは頭の下のすべてのメッシュを共通の頭マテリアルで描画します。パーツのテクスチャは顔・目・口・チークの領域を避けて頭テクスチャの空きに収める必要があり、アトラスは作らず、顔も一緒に読み込む必要があります。Bodyと頭のメッシュは同じ順序・同じアウトラインで描画されます。",
        "Reuse original UV positions": "元のUV位置を再利用",
        "Match corresponding main, rimlight and other UV textures to the larger resolution and keep the original UV positions. If those positions are occupied, use a new atlas. Head meshes are never combined into an atlas. No padding is added.": "メイン・リムライトなど対応する画像をそれぞれ大きい方の解像度に合わせ、元のUV位置を維持します。その位置が使用中なら新しいアトラスに結合します。頭のメッシュはアトラスに結合しません。パディングは追加しません。",
        "Move into empty UV areas": "空きUV領域へ移動",
        "Keep main-texture resolution, match auxiliary-map ratios, and move each selected UV island with its textures into unused space. If no space fits, use a new atlas. Head meshes are never combined into an atlas. No padding is added.": "メインテクスチャの解像度を維持し、補助マップの比率を合わせて、選択したUVアイランドごとにテクスチャと一緒に空き領域へ移動します。収まる空間がなければ新しいアトラスに結合します。頭のメッシュはアトラスに結合しません。パディングは追加しません。",
        "Build a new texture atlas": "新しいテクスチャアトラスを作成",
        "Combine textures into a new atlas and remap UVs. Not available for head meshes. No padding is added.": "テクスチャを新しいアトラスに結合し、UVを再配置します。頭のメッシュには使用できません。パディングは追加しません。",
        "Before either UV reuse method, enlarge corresponding main, rimlight and other UV textures to the larger resolution. No padding is added.":
            "どちらのUV再利用方式でも、メイン・リムライトなど対応するUVテクスチャを大きい方の解像度に先に拡大します。パディングは追加しません。",
        "If the original UV position is occupied, find another empty area without reducing source pixel detail. No padding is added.":
            "元のUV位置が使用中なら、元画像の細部を維持して別の空き領域を探します。パディングは追加しません。",
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
        "Lift the open cap to close gaps above a shorter lower body. Open caps require a new texture atlas. Use 0 for a flat cap.":
            "短い下半身との隙間を埋めるにはキャップを持ち上げます。開いたキャップには新しいテクスチャアトラスが必要です。平らなキャップは0に設定します。",
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
        "화면에 맞춤",
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
    "Open a costume model or ZIP. Its preview pose and missing face parts load automatically.": [
        "의상 모델이나 ZIP을 열면 미리보기 포즈와 빠진 얼굴 파츠를 자동으로 불러옵니다.",
        "衣装モデルやZIPを開くと、プレビュー姿勢と不足した顔パーツを自動で読み込みます。"
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
    "The original face is unavailable. The costume is still shown; check the asset connection and try again.": [
        "원본 얼굴을 불러오지 못했습니다. 의상은 계속 표시됩니다. 리소스 서버 연결을 확인한 뒤 다시 열어주세요.",
        "元の顔を取得できませんでした。衣装は引き続き表示されます。リソース配信サーバーへの接続を確認して、もう一度開いてください。"
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
    "Missing face parts are found locally or downloaded automatically.": [
        "빠진 얼굴은 저장된 원본에서 찾고, 없으면 자동으로 내려받습니다.",
        "不足した顔パーツを保存済みデータから探し、必要に応じて元データを自動取得します。"
    ]
})
_VIEWER_TRANSLATIONS.update({
    "Pose and body": ["포즈·체형 조절", "ポーズ・体型調整"],
    "Pose and motion": ["포즈·모션", "ポーズ・モーション"],
    "Reset pose, body and expressions": ["포즈·체형·표정 초기화", "ポーズ・体型・表情をリセット"],
    "Add custom motion": ["다른 모션 추가", "別のモーションを追加"],
    "The SIFAS preview pose loads automatically. You can add custom Unity motion/expression bundles. FBX motion files are not supported.": ["SIFAS 미리보기 포즈를 자동으로 불러옵니다. 다른 모션·표정은 Unity 번들로 추가할 수 있습니다. FBX 모션은 지원하지 않습니다.", "SIFASプレビュー姿勢を自動で読み込みます。別のモーション・表情はUnityバンドルで追加できます。FBXモーションには対応していません。"],
    "Use saved node settings": ["파일의 노드 설정 적용", "ファイルのノード設定を適用"],
    "Uses verified scale and position values from the file. Game height normalization is not applied.": ["파일에서 확인한 크기·위치 값을 적용합니다. 게임의 키 정규화는 적용하지 않습니다.", "ファイルで確認できたサイズ・位置の値を適用します。ゲームの身長正規化は適用しません。"],
    "100% adds no extra size change. Adjustments follow the selected pose and saved-settings option.": ["100%는 크기를 추가로 바꾸지 않습니다. 선택한 자세와 노드 설정을 기준으로 조절합니다.", "100%ではサイズを追加変更しません。選択した姿勢とノード設定を基準に調整します。"],
    "No verified saved node settings are available.": ["적용할 수 있는 노드 설정이 파일에 없습니다.", "適用できるノード設定がファイルにありません。"],
    "Saved node settings are applied. 100% adds no extra scaling.": ["파일의 노드 설정을 적용했습니다. 100%는 크기를 추가로 바꾸지 않습니다.", "ファイルのノード設定を適用しています。100%ではサイズを追加変更しません。"],
    "Using the file's authored shape. Saved node settings are off.": ["파일의 원래 체형을 표시합니다. 노드 설정은 적용하지 않았습니다.", "ファイルの元の体型を表示しています。ノード設定は未適用です。"],
    "Unsupported or conflicting saved settings were skipped.": ["지원하지 않거나 서로 충돌하는 설정은 건너뛰었습니다.", "未対応または競合する設定はスキップしました。"],
    "Relative to the selected pose and body settings.": ["선택한 자세와 체형 설정을 기준으로 조절합니다.", "選択した姿勢と体型設定を基準に調整します。"],
    "Saved height setting": ["게임에 저장할 키 설정", "ゲームに保存する身長設定"],
    "Sets the game's saved heightScale value (0.1–3). Blank keeps it. This is separate from the viewer's height percentage.": ["게임용 heightScale 값(0.1~3)을 저장합니다. 비워 두면 유지합니다. 뷰어의 키 퍼센트와는 별도입니다.", "ゲーム用のheightScale値（0.1～3）を保存します。空欄なら変更しません。ビューアーの身長パーセントとは別の設定です。"],
    "Saved height setting must be between 0.1 and 3.": ["게임에 저장할 키 설정은 0.1~3 사이여야 합니다.", "ゲームに保存する身長設定は0.1～3の範囲で指定してください。"],
    "No saved height component was found in this bundle.": ["이 번들에서 게임용 키 설정 항목을 찾지 못했습니다.", "このバンドルにゲーム用の身長設定項目が見つかりません。"],
    "Preview only. The original files stay unchanged.": ["미리보기에만 적용되며 원본 파일은 바뀌지 않습니다.", "プレビューだけに適用され、元のファイルは変更されません。"],
    "Pose / motion": ["포즈 / 모션", "ポーズ／モーション"],
    "SIFAS costume preview": ["SIFAS 의상 미리보기", "SIFAS衣装プレビュー"],
    "Pose": ["자세", "姿勢"],
    "Basic pose": ["기본 자세", "基本姿勢"],
    "Posed view": ["포즈 자세", "プレビュー姿勢"],
    "No compatible preview motion is available.": ["이 모델에서 사용할 수 있는 포즈 모션이 없습니다.", "このモデルに対応するプレビューモーションがありません。"],
    "Apply saved body and outfit settings": ["파일의 체형·의상 설정 적용", "保存された体型・衣装設定を適用"],
    "Uses verified size, position and rotation settings from the file. Game height normalization is not applied.": ["파일에서 확인한 크기·위치·회전 설정을 적용합니다. 게임의 키 정규화는 적용하지 않습니다.", "ファイルで確認できたサイズ・位置・回転設定を適用します。ゲームの身長正規化は適用しません。"],
    "Parts in saved settings": ["설정이 적용되는 부위", "設定を適用する部位"],
    "Applied settings": ["적용한 설정", "適用した設定"],
    "Skirt": ["치마", "スカート"],
    "Head": ["머리", "頭"],
    "Hair": ["머리카락", "髪"],
    "Eyes": ["눈", "目"],
    "Torso": ["몸통", "胴体"],
    "Arms": ["팔", "腕"],
    "Hands": ["손", "手"],
    "Legs": ["다리", "脚"],
    "Feet": ["발", "足"],
    "Saved pose": ["파일에 저장된 자세", "ファイルに保存された姿勢"],
    "Play": ["재생", "再生"],
    "Pause": ["일시 정지", "一時停止"],
    "Motion time": ["모션 재생 위치", "モーションの再生位置"],
    "Height": ["키", "身長"],
    "Breast size": ["가슴 크기", "胸のサイズ"],
    "100% keeps the model's saved body shape. Adjustments follow the selected pose.": ["100%는 파일에 저장된 체형입니다. 선택한 자세에 크기 조절을 더해 표시합니다.", "100%はファイルに保存された体型です。選択した姿勢にサイズ調整を加えて表示します。"],
    "Expression channel": ["표정 파츠", "表情パーツ"],
    "Expression strength": ["표정 강도", "表情の強さ"],
    "Too many expression channels are active. Some may be omitted by the viewer.": ["동시에 적용한 표정이 많아 일부는 뷰어에서 표시되지 않을 수 있습니다.", "同時に有効な表情が多いため、一部はビューアーで表示されない場合があります。"],
    "Individual bones (advanced)": ["개별 본 조절 (고급)", "ボーンごとの調整（上級）"],
    "Changes are relative to the current pose. Movement uses the model's local units.": ["현재 자세를 기준으로 조절합니다. 이동 단위는 모델의 로컬 좌표입니다.", "現在の姿勢を基準に調整します。移動量はモデルのローカル座標単位です。"],
    "Scale (%)": ["크기 (%)", "サイズ（%）"],
    "Reset this bone": ["이 본 초기화", "このボーンをリセット"],
    "Reset preview adjustments": ["포즈·체형 초기화", "ポーズ・体型をリセット"],
    "No expression channels in this model.": ["이 모델에 표정 채널이 없습니다.", "このモデルに表情チャンネルはありません。"],
    "No editable bones in this model.": ["조절할 수 있는 본이 없습니다.", "調整できるボーンはありません。"],
    "Play or pause a motion to inspect the model's pose.": ["모션을 재생하거나 멈춰서 모델의 자세를 확인하세요.", "モーションを再生または停止して、モデルの姿勢を確認できます。"],
    "No compatible motion is available. You can adjust this model's bones and expressions.": ["이 모델에서 사용할 수 있는 모션이 없습니다. 본과 표정은 조절할 수 있습니다.", "このモデルに対応するモーションがありません。ボーンや表情は調整できます。"],
    "This model supports a static preview only.": ["이 모델은 정적인 모습만 표시할 수 있습니다.", "このモデルは静止した状態のプレビューに対応しています。"],
    "Relative to the model's saved size.": ["파일에 저장된 크기를 기준으로 조절합니다.", "ファイルに保存されたサイズを基準に調整します。"],
    "This model has no supported height control.": ["이 모델에는 확인된 키 조절 정보가 없습니다.", "このモデルには確認済みの身長調整情報がありません。"],
    "This model has no verified breast-size node.": ["이 모델에는 확인된 가슴 크기 노드가 없습니다.", "このモデルには確認済みの胸サイズノードがありません。"],
    "Materials": ["재질", "マテリアル"],
    "High-quality 3D": ["고퀄리티 3D", "3Dなめらか"],
    "Uses your device's resolution and smoother model edges.": ["기기 해상도에 맞춰 모델을 표시하고 윤곽선을 부드럽게 합니다.", "端末の解像度でモデルを表示し、輪郭をなめらかにします。"],
    "Device-resolution rendering is enabled; edge smoothing is unavailable on this device.": ["기기 해상도로 표시 중입니다. 이 기기에서는 윤곽선 보정을 지원하지 않습니다.", "端末の解像度で表示しています。この端末では輪郭のなめらか表示に対応していません。"],
    "SIFAS material preview": ["SIFAS 재질 미리보기", "SIFASマテリアルプレビュー"],
    "SIFAS material data is unavailable. Basic textures are shown.": ["SIFAS 재질 정보가 없어 기본 텍스처로 표시합니다.", "SIFASマテリアル情報がないため、基本テクスチャで表示しています。"],
    "Basic textures are shown.": ["기본 텍스처로 표시합니다.", "基本テクスチャで表示しています。"],
    "Uses the file's SIFAS material settings. In-game appearance may differ.": ["파일의 SIFAS 재질 설정을 사용합니다. 게임 속 모습과는 차이가 날 수 있습니다.", "ファイルのSIFASマテリアル設定を使います。ゲーム内の見た目とは異なる場合があります。"],
    "Basic textures": ["기본 텍스처", "基本テクスチャ"],
    "Game lighting and motion may look different. Available controls depend on the model's data.": ["게임의 조명·모션과 차이가 날 수 있습니다. 모델에 포함된 데이터에 따라 조절 기능이 달라집니다.", "ゲームの照明や動きとは異なる場合があります。調整できる項目はモデル内のデータによって変わります。"],
})
_VIEWER_TRANSLATIONS.update({
    "Body and outfit": ["체형·의상", "体型・衣装"],
    "Height (%)": ["키 (%)", "身長（%）"],
    "Breast size (%)": ["가슴 크기 (%)", "胸のサイズ（%）"],
    "Skirt length and flare": ["치마 길이·퍼짐", "スカート丈・広がり"],
    "Skirt length and flare (%)": ["치마 길이·퍼짐 (%)", "スカート丈・広がり（%）"],
    "Adjust height vertically while keeping head proportions.": ["머리 비율을 유지하며 세로 키를 조절합니다.", "頭の比率を保ちながら縦方向の身長を調整します。"],
    "Uses the breast tool's proportions for width, height and depth.": ["가슴 변경 도구와 같은 너비·높이·깊이 비율로 조절합니다.", "胸サイズ変更ツールと同じ幅・高さ・奥行きの比率で調整します。"],
    "Adjusts the skirt sections together using the skirt tool's settings.": ["치마 변경 도구처럼 치마의 각 부위를 함께 조절합니다.", "スカート変更ツールと同じ設定で各部分をまとめて調整します。"],
    "100% keeps the loaded settings. Each reset restores that part's loaded value.": ["100%는 불러온 설정입니다. 초기화하면 해당 부위만 불러온 값으로 돌아갑니다.", "100%は読み込んだ設定です。リセットするとその部分だけ読み込み時の値に戻ります。"],
    "Apply settings saved in the file": ["파일에 저장된 보정 적용", "ファイルに保存された補正を適用"],
    "Loads the file's size, position and rotation corrections.": ["파일에 저장된 크기·위치·회전 보정을 불러옵니다.", "ファイルに保存されたサイズ・位置・回転補正を読み込みます。"],
    "Body presets": ["체형 프리셋", "体型プリセット"],
    "Facial expression": ["표정", "表情"],
    "Reset expression": ["표정 초기화", "表情をリセット"],
    "Fine-tune expression parts": ["표정 파츠 세부 조절", "表情パーツの詳細調整"],
    "Expression part": ["표정 파츠", "表情パーツ"],
    "Common adjustments": ["자주 쓰는 부위", "よく使う部分"],
    "Find a bone": ["부위·본 찾기", "部位・ボーンを検索"],
    "Search by body part or bone name": ["부위 또는 본 이름 검색", "部位名またはボーン名で検索"],
    "Show bones": ["목록 표시", "表示するボーン"],
    "All bones": ["모든 본", "すべてのボーン"],
    "With saved settings": ["파일에 보정된 본", "保存済み補正のあるボーン"],
    "My changes": ["내가 바꾼 본", "自分で変更したボーン"],
    "Frequently adjusted": ["자주 쓰는 본", "よく使うボーン"],
    "Saved and changed bones": ["파일 보정·내가 바꾼 본", "保存済み補正・変更したボーン"],
    "Fields show the loaded corrections and your changes. Animation does not overwrite these values.": ["입력값은 파일·체형 보정 기준입니다. 재생 중인 포즈의 순간 값은 바꾸지 않습니다.", "入力値はファイル・体型補正を基準にしています。再生中の姿勢の瞬間値は変更しません。"],
    "Local axes: X width, Y height, Z depth. Rotation follows Unity's bone coordinates.": ["로컬 축은 X 너비·Y 높이·Z 깊이입니다. 회전은 Unity 본 좌표를 따릅니다.", "ローカル軸はXが幅、Yが高さ、Zが奥行きです。回転はUnityのボーン座標に従います。"],
    "Loaded value": ["불러온 값", "読み込んだ値"],
    "Current value": ["현재 값", "現在の値"],
    "File correction": ["파일 보정", "保存済み補正"],
    "Your change": ["내 변경", "自分の変更"],
    "No matching bones.": ["조건에 맞는 본이 없습니다.", "条件に一致するボーンがありません。"],
    "No changed bones.": ["추가로 변경한 본이 없습니다.", "追加で変更したボーンはありません。"],
    "Width (X)": ["너비 (X)", "幅（X）"],
    "Height (Y)": ["높이 (Y)", "高さ（Y）"],
    "Depth (Z)": ["깊이 (Z)", "奥行き（Z）"],
    "Brows": ["눈썹", "眉"],
    "Mouth": ["입", "口"],
    "Other parts": ["기타 파츠", "その他のパーツ"],
})
_VIEWER_TRANSLATIONS.update({
    "Eyes and brows": ["눈·눈썹", "目・眉"],
    "Eye details": ["눈 세부 조절", "目の詳細調整"],
    "Other expression channels": ["기타 표정 파츠", "その他の表情パーツ"],
    "Closed eyelids": ["눈꺼풀 감기", "まぶたを閉じる"],
    "Narrowed eyelids": ["눈꺼풀 가늘게", "まぶたを細める"],
    "Open eyelids": ["눈꺼풀 열기", "まぶたを開く"],
    "Wide eyes": ["크게 뜬 눈", "大きく開いた目"],
    "Smiling closed eyelids": ["웃으며 감은 눈", "笑って閉じた目"],
    "Right wink shape": ["오른눈 윙크 모양", "右目のウィンク形状"],
    "Left wink shape": ["왼눈 윙크 모양", "左目のウィンク形状"],
    "Troubled eyes": ["곤란한 눈", "困った目"],
    "Sad eyes": ["슬픈 눈", "悲しい目"],
    "Angry eyes": ["화난 눈", "怒った目"],
    "Shy eyes": ["수줍은 눈", "照れた目"],
    "Tightly closed eyelids": ["꾹 감은 눈꺼풀", "ぎゅっと閉じたまぶた"],
    "A mouth": ["아 발음", "あの口"],
    "I mouth": ["이 발음", "いの口"],
    "U mouth": ["우 발음", "うの口"],
    "E mouth": ["에 발음", "えの口"],
    "O mouth": ["오 발음", "おの口"],
    "Closed mouth": ["다문 입", "閉じた口"],
    "Smiling mouth": ["미소 짓는 입", "微笑んだ口"],
    "Laughing mouth": ["웃는 입", "笑った口"],
    "Troubled mouth": ["곤란한 입", "困った口"],
    "Sad mouth": ["슬픈 입", "悲しい口"],
    "Angry mouth": ["화난 입", "怒った口"],
    "Shy mouth": ["수줍은 입", "照れた口"],
    "Eyes open": ["눈 뜨기", "目を開く"],
    "Eyes closed": ["눈 감기", "目を閉じる"],
    "Narrow eyes": ["가늘게 뜬 눈", "細めた目"],
    "Eyes wide open": ["눈 크게 뜨기", "目を大きく開く"],
    "Smiling eyes": ["웃는 눈", "笑った目"],
    "Right wink": ["오른눈 윙크", "右目のウィンク"],
    "Left wink": ["왼눈 윙크", "左目のウィンク"],
    "Eyes tightly closed": ["눈 꾹 감기", "目をぎゅっと閉じる"],
    "Smile": ["미소", "微笑み"],
    "Laugh": ["웃음", "笑い"],
    "Sad": ["슬픔", "悲しみ"],
    "Angry": ["화남", "怒り"],
    "Shy": ["수줍음", "照れ"],
    "Shape channel": ["모양 파츠", "形状パーツ"],
    "Left eye detail": ["왼눈 세부", "左目の詳細"],
    "Right eye detail": ["오른눈 세부", "右目の詳細"],
    "Unidentified eye shape": ["미확인 눈 모양", "未確認の目の形状"],
    "Unidentified mouth shape": ["미확인 입 모양", "未確認の口の形状"],
    "Shape control only.": ["모양만 조절합니다.", "形状のみを調整します。"],
    "Shared eyelid shape; gaze is controlled separately.": ["공통 눈꺼풀 모양입니다. 시선은 별도로 조절합니다.", "共通のまぶた形状です。視線は別に調整します。"],
    "Original game eye pose for this verified face.": ["이 얼굴에서 확인한 게임 원본 눈 표정입니다.", "この顔で確認済みのゲーム本来の目の表情です。"],
    "A viewer combination of verified eye and mouth shapes.": ["확인된 눈·입 모양을 뷰어에서 조합한 표정입니다.", "確認済みの目と口の形状をビューアーで組み合わせた表情です。"],
    "Original expression channel name is available in advanced controls.": ["원본 표정 파츠 이름은 고급 조절에서 확인할 수 있습니다.", "元の表情パーツ名は詳細調整で確認できます。"],
    "Skirt length and volume": ["치마 길이·퍼짐", "スカート丈・広がり"],
    "Stock": ["표준형", "標準"],
    "Yoshiko/Shioriko": ["요시코/시오리코", "善子/栞子"],
    "Honoka/Maki": ["호노카/마키", "穂乃果/真姫"],
    "Umi/Ruby/Kasumi": ["우미/루비/카스미", "海未/ルビィ/かすみ"],
    "Rin": ["린", "凛"],
    "Nico": ["니코", "にこ"],
    "Rina": ["리나", "璃奈"],
    "Chika/You/Ayumu": ["치카/요우/아유무", "千歌/曜/歩夢"],
    "Hanayo/Setsuna": ["하나요/세츠나", "花陽/せつ菜"],
    "Hanamaru/Ai": ["하나마루/아이", "花丸/愛"],
    "Lanzhu": ["란쥬", "ランジュ"],
    "Eli/Kanan/Kanata": ["에리/카난/카나타", "絵里/果南/彼方"],
    "Mari": ["마리", "鞠莉"],
    "Karin": ["카린", "果林"],
    "Nozomi": ["노조미", "希"],
    "Emma": ["엠마", "エマ"],
    "Back hair": ["뒷머리", "後ろ髪"],
    "Hip size": ["엉덩이 크기", "ヒップサイズ"],
    "Lower torso": ["몸통 아래", "胴体下部"],
    "Middle torso": ["몸통 가운데", "胴体中央"],
    "Upper torso": ["몸통 위", "胴体上部"],
    "Left upper arm": ["왼쪽 위팔", "左上腕"],
    "Right upper arm": ["오른쪽 위팔", "右上腕"],
    "Left forearm": ["왼쪽 아래팔", "左前腕"],
    "Right forearm": ["오른쪽 아래팔", "右前腕"],
    "Left hand": ["왼손", "左手"],
    "Right hand": ["오른손", "右手"],
    "Left thigh": ["왼쪽 허벅지", "左太もも"],
    "Right thigh": ["오른쪽 허벅지", "右太もも"],
    "Left calf": ["왼쪽 종아리", "左ふくらはぎ"],
    "Right calf": ["오른쪽 종아리", "右ふくらはぎ"],
    "Left foot": ["왼발", "左足"],
    "Right foot": ["오른발", "右足"],
    "Left shoulder": ["왼쪽 어깨", "左肩"],
    "Right shoulder": ["오른쪽 어깨", "右肩"],
    "Breast placement": ["가슴 위치", "胸の位置"],
})
_VIEWER_TRANSLATIONS.update({
    "This model has no supported skirt roots.": ["이 모델에는 조절할 수 있는 치마 본이 없습니다.", "このモデルには調整に対応したスカートのボーンがありません。"],
    "This custom breast size is outside the tool curve. Use individual bone editing.": ["현재 가슴 비율은 도구의 표준 비율과 다릅니다. 개별 본 조절을 사용하세요.", "この胸の比率はツールの標準比率と異なります。ボーンごとの調整を使ってください。"],
    "Changes vertical body height while keeping the head and hair proportions.": ["머리·머리카락 비율을 유지하며 몸의 세로 키를 조절합니다.", "頭と髪の比率を保ちながら、体の縦方向の身長を調整します。"],
    "Width follows the breast tool curve; height and depth adjust proportionally.": ["너비를 기준으로 가슴 도구의 비율에 따라 높이·깊이도 조절합니다.", "幅を基準に、胸サイズ変更ツールの比率に沿って高さと奥行きも調整します。"],
    "Uses the skirt tool's root bones. Length and flare change together.": ["치마 도구와 같은 방식으로 길이와 퍼짐을 함께 바꿉니다.", "スカートツールと同じ方法で、丈と広がりをまとめて変えます。"],
    "Breast tool presets": ["가슴 도구 프리셋", "胸サイズ変更ツールのプリセット"],
    "Loaded shape": ["불러온 체형", "読み込んだ体型"],
    "Saved settings": ["저장된 보정값", "保存済み補正"],
    "Body adjustment": ["체형 조절", "体型調整"],
    "No matching bones": ["조건에 맞는 본이 없습니다.", "条件に一致するボーンがありません。"],
    "No recommended bones in this model.": ["이 모델에는 추천할 수 있는 본이 없습니다.", "このモデルには推奨できるボーンがありません。"],
    "Choose a bone to edit.": ["조절할 본을 선택하세요.", "調整するボーンを選んでください。"],
    "Loaded baseline": ["불러온 기준값", "読み込んだ基準値"],
    "Position (model units)": ["이동 (모델 단위)", "移動（モデル単位）"],
    "Waist and torso": ["허리·몸통", "ウエスト・胴体"],
    "Upper body": ["상체", "上半身"],
    "Left arm": ["왼팔", "左腕"],
    "Right arm": ["오른팔", "右腕"],
    "Full face": ["얼굴 전체", "顔全体"],
    "Expression shapes": ["표정 모양", "表情の形状"],
    "Fine-tune shapes": ["모양 세부 조절", "形状の詳細調整"],
    "Select an expression part": ["표정 파츠 선택", "表情パーツを選択"],
    "Only original channel names are available for this model.": ["이 모델은 원본 표정 파츠 이름으로만 조절할 수 있습니다.", "このモデルは元の表情パーツ名でのみ調整できます。"],
    "Some expression presets are unavailable for this model.": ["이 모델에서는 일부 표정 프리셋을 사용할 수 없습니다.", "このモデルでは一部の表情プリセットを使用できません。"],
    "Expression parts": ["표정 파츠", "表情パーツ"],
    "Mixed values": ["서로 다른 값", "異なる値"],
    "Original channel": ["원본 채널", "元のチャンネル"],
    "Expression preset": ["표정 프리셋", "表情プリセット"],
    "Expression shape": ["표정 모양", "表情の形状"],
})
_VIEWER_TRANSLATIONS.update({
    "Look right": ["오른쪽 보기", "右を見る"],
    "Look left": ["왼쪽 보기", "左を見る"],
    "Look up": ["위 보기", "上を見る"],
    "Look down": ["아래 보기", "下を見る"],
    "Look up and right": ["오른쪽 위 보기", "右上を見る"],
    "Look up and left": ["왼쪽 위 보기", "左上を見る"],
    "Blink": ["눈 깜빡이기", "まばたき"],
})
_VIEWER_TRANSLATIONS.update({
    "File saved value": ["파일에 저장된 값", "ファイルに保存された値"],
    "Not applied": ["미적용", "未適用"],
    "File and body baseline": ["파일·체형 기준값", "ファイル・体型の基準値"],
    "Zero-scale axes cannot be edited safely.": ["배율이 0인 축은 안전하게 조절할 수 없습니다.", "倍率が 0 の軸は安全に調整できません。"],
})
_VIEWER_TRANSLATIONS.update({
    "Height settings in the file": ["파일의 키 설정", "ファイルの身長設定"],
    "Read-only": ["보기만 가능", "表示のみ"],
    "Height adjustment is unavailable. Saved values are shown for reference.": ["키를 직접 조절하는 기능은 지원하지 않습니다. 파일에 저장된 값만 참고용으로 표시합니다.", "身長の直接調整には対応していません。ファイルに保存された値を参考情報として表示します。"],
    "Reference body profile": ["기준 체형 선택", "基準体型を選択"],
    "Loaded profile": ["파일의 체형", "ファイルの体型"],
    "Current profile": ["현재 체형", "現在の体型"],
    "Restore loaded shape": ["파일의 체형으로 복원", "ファイルの体型に戻す"],
    "Smaller profiles": ["표준보다 작은 체형", "標準より小さめの体型"],
    "Larger profiles": ["표준보다 큰 체형", "標準より大きめの体型"],
    "Custom shape": ["사용자 설정", "カスタム設定"],
    "Character names identify the breast tool's reference settings. They do not change the character.": ["이름은 가슴 도구의 기준 체형을 뜻합니다. 캐릭터는 바뀌지 않습니다.", "名前は胸サイズ変更ツールの基準体型を表します。キャラクターは変わりません。"],
    "Skirt 100% keeps the loaded skirt settings. Reset restores the loaded skirt shape.": ["치마 100%는 파일의 치마 설정을 유지합니다. 초기화하면 파일의 치마 모양으로 돌아갑니다.", "スカートの100%はファイルの設定を維持します。リセットするとファイルのスカート形状に戻ります。"],
    "Whole model": ["모델 전체", "モデル全体"],
    "Reference baseline": ["도구 기준형", "ツールの基準体型"],
    "Uses file settings": ["파일 설정 유지", "ファイルの設定を使用"],
    "Current shape": ["현재 체형", "現在の体型"],
    "File settings are off": ["파일 보정 적용 안 함", "ファイルの補正は未適用"],
    "Saved height metadata": ["파일의 heightScale 값", "ファイルのheightScale値"],
    "Height correction unavailable": ["키 보정 조절 미지원", "身長補正の調整は未対応"],
    "Below reference baseline": ["기준 형태보다 작음", "基準形状より小さい"],
    "Above reference baseline": ["기준 형태보다 큼", "基準形状より大きい"],
    "Saved node settings are applied.": ["파일에 저장된 본 보정을 적용했습니다.", "ファイルに保存されたボーン補正を適用しました。"],
})
_VIEWER_TRANSLATIONS.update({
    "File values": ["파일 값", "ファイルの値"],
    "Current editing values (before animation)": ["현재 편집값 (모션 적용 전)", "現在の編集値（モーション適用前）"],
    "Current values": ["현재 값", "現在の値"],
    "Current values are editing values before animation.": ["현재 값은 모션 적용 전 편집값입니다.", "現在の値はモーション適用前の編集値です。"],
    "Editing values are calculated before animation. Pose values are shown separately.": ["편집값은 모션 적용 전에 계산합니다. 포즈 값은 따로 표시합니다.", "編集値はモーション適用前に計算します。姿勢の値は別に表示します。"],
    "Scale factor": ["배율", "倍率"],
    "XYZ scale factors": ["XYZ 배율", "XYZ倍率"],
    "Apply this value to every skirt root": ["모든 치마 부분에 적용", "すべてのスカート部分に適用"],
    "Undo skirt edits": ["치마 편집 되돌리기", "スカートの編集を取り消す"],
    "Undo breast scale edits": ["가슴 배율 편집 되돌리기", "胸の倍率編集を取り消す"],
    "Per-bone values": ["부분별 값", "部分ごとの値"],
    "The entered value sets X, Y and Z of every skirt root to the same scale.": ["입력한 배율을 모든 치마 부분의 X·Y·Z에 똑같이 적용합니다.", "入力した倍率をすべてのスカート部分のX・Y・Zに同じように適用します。"],
    "File values stay unchanged when you edit the preview or turn saved settings off.": ["미리보기를 편집하거나 파일 보정을 꺼도 파일 값은 바뀌지 않습니다.", "プレビューを編集したり保存済み補正をオフにしたりしても、ファイルの値は変わりません。"],
    "File profile": ["파일의 체형", "ファイルの体型"],
    "Saved heightScale (reference only)": ["파일의 heightScale (참고용)", "ファイルのheightScale（参考情報）"],
    "This saved parameter is not a measurement in centimetres or the current model height.": ["cm 단위의 키나 현재 모델 높이를 뜻하는 값은 아닙니다.", "この保存パラメーターは、センチメートル単位の身長や現在のモデルの高さを表す値ではありません。"],
    "Each bone uses local X, Y and Z axes. Their directions may differ from the model axes.": ["각 본의 X·Y·Z는 로컬 축입니다. 모델 전체의 축 방향과 다를 수 있습니다.", "各ボーンのX・Y・Zはローカル軸です。モデル全体の軸方向とは異なる場合があります。"],
    "Current expression weight (%)": ["현재 표정 강도 (%)", "現在の表情の強さ（%）"],
    "File and current expression weights": ["파일·현재 표정 강도", "ファイル・現在の表情の強さ"],
    "Expression weights are separate from bone scale factors.": ["표정 강도와 본 배율은 별도 값입니다.", "表情の強さとボーン倍率は別の値です。"],
    "Conflicting file values": ["파일 값 충돌", "ファイルの値が競合"],
    "No saved correction": ["저장된 보정 없음", "保存済み補正なし"],
    "Authored bone values": ["파일의 기본 본 값", "ファイルの基本ボーン値"],
    "Values in current pose": ["현재 포즈 값", "現在の姿勢の値"],
    "Undo manual bone edits": ["직접 입력한 본 편집 되돌리기", "手動のボーン編集を取り消す"],
    "Scale (local factor)": ["배율 (로컬 값)", "倍率（ローカル値）"],
    "File authored value": ["파일의 기본 본 값", "ファイルの基本ボーン値"],
    "File value unavailable": ["파일 값 확인 불가", "ファイルの値を確認できません"],
    "Unsupported file value": ["지원하지 않는 파일 값", "未対応のファイル値"],
    "Current editing value": ["현재 편집값", "現在の編集値"],
    "Game initial value": ["게임 초기값", "ゲーム初期値"],
    "Current pose value": ["현재 포즈 값", "現在の姿勢の値"],
    "Partially supported motion": ["일부만 지원되는 모션", "一部のみ対応しているモーション"],
    "Some animation tracks could not be applied.": ["일부 모션 트랙은 적용하지 못했습니다.", "一部のモーショントラックは適用できませんでした。"],
    "File weight": ["파일의 표정 강도", "ファイルの表情の強さ"],
    "Current weight": ["현재 표정 강도", "現在の表情の強さ"],
    "Select an expression part": ["표정 부위를 선택하세요.", "表情の部位を選択してください。"],
    "Editing this shape replaces mixed values.": ["직접 조절하면 서로 다른 값을 새 값으로 맞춥니다.", "この形状を調整すると、異なる値が新しい値に統一されます。"],
    "Part visibility follows the current pose.": ["부분 표시 여부는 현재 포즈에 따릅니다.", "パーツの表示は現在の姿勢に従います。"],
    "No extra edits": ["추가 편집 없음", "追加編集なし"],
    "Different values": ["서로 다른 값", "異なる値"],
    "Skirt scale must be between 0.01 and 10.": ["치마 배율은 0.01~10 사이여야 합니다.", "スカートの倍率は0.01から10の範囲で指定してください。"],
    "Authored fallback": ["기본 본 값 사용", "基本ボーン値を使用"],
    "File values not applied": ["파일 값 미적용", "ファイルの値は未適用"],
    "Expression weight must be a finite number between -10000% and 10000%.": ["표정 강도는 -10000%~10000% 사이의 유효한 숫자여야 합니다.", "表情の強さには-10000%から10000%の範囲で有限の数値を入力してください。"],
    "Set shape to 100%": ["이 표정을 100%로 설정", "この表情を100%に設定"],
    "heightScale metadata": ["heightScale 메타데이터", "heightScaleメタデータ"],
    "File visibility": ["파일의 표시 상태", "ファイルの表示状態"],
    "Current visibility": ["현재 표시 상태", "現在の表示状態"],
    "Your visibility choice": ["직접 선택한 표시 상태", "手動で選択した表示状態"],
    "Visible": ["표시", "表示"],
    "Hidden": ["숨김", "非表示"],
})
_VIEWER_TRANSLATIONS.update({
    "Full screen": ["전체 화면", "全画面表示"],
    "Exit full screen": ["전체 화면 닫기", "全画面表示を終了"],
    "Model information": ["모델 정보", "モデル情報"],
    "Model options": ["모델 옵션", "モデル設定"],
    "View controls": ["보기 설정", "表示操作"],
    "Files and app controls": ["파일·앱 메뉴", "ファイル・アプリ操作"],
    "Compensate child bone scale": ["하위 본 배율 보정", "子ボーンの倍率を補正"],
    "Compensation targets": ["보정 대상", "補正対象"],
    "Immediate child bones (auto)": ["바로 아래 본 (자동)", "直下の子ボーン（自動）"],
    "Child compensation is off.": ["하위 본 배율 보정이 꺼져 있습니다.", "子ボーンの倍率補正はオフです。"],
    "Child compensation is ready; change this bone’s scale to activate it.": ["이 본의 배율을 바꾸면 하위 본을 보정합니다.", "このボーンの倍率を変更すると、子ボーンを補正します。"],
    "Child compensation is active.": ["하위 본 배율 보정을 적용 중입니다.", "子ボーンの倍率を補正中です。"],
    "Child compensation is unavailable.": ["이 설정에는 하위 본 배율 보정을 적용할 수 없습니다.", "この設定には子ボーンの倍率補正を適用できません。"],
    "Targets": ["대상", "対象"],
    "No descendant bone matches this target choice.": ["선택한 대상에 해당하는 하위 본이 없습니다.", "選択した対象に一致する子孫ボーンがありません。"],
    "The target name is ambiguous in this bone’s descendants.": ["같은 이름의 하위 본이 여러 개여서 대상을 정할 수 없습니다.", "同名の子孫ボーンが複数あるため、対象を特定できません。"],
    "A baseline transform has zero or invalid scale.": ["기준 본의 배율이 0이거나 올바르지 않습니다.", "基準ボーンの倍率が0、または無効です。"],
    "The edited scale cannot be inverted.": ["입력한 배율의 역보정을 계산할 수 없습니다.", "入力した倍率の逆補正を計算できません。"],
    "Automatic affine compensation": ["자동 행렬 보정", "自動行列補正"],
    "Includes shear; manual TRS values stay unchanged.": ["기울어짐 보정을 포함합니다. 직접 입력한 이동·회전·배율 값은 유지합니다.", "せん断補正を含みます。手動入力した移動・回転・倍率の値は維持します。"],
    "Manual TRS values stay unchanged.": ["직접 입력한 이동·회전·배율 값은 유지합니다.", "手動入力した移動・回転・倍率の値は維持します。"],
    "No automatic compensation on this bone.": ["이 본에는 자동 보정이 적용되지 않았습니다.", "このボーンには自動補正が適用されていません。"],
    "Incoming automatic compensation": ["상위 본에서 받은 자동 보정", "親ボーンから受ける自動補正"],
    "No compensation was applied.": ["보정은 적용하지 않았습니다.", "補正は適用されませんでした。"],
    "Full screen is unavailable here. Expanded view is open.": ["전체 화면을 사용할 수 없어 크게 보기를 열었습니다.", "ここでは全画面表示を利用できないため、拡大表示を開きました。"],
    "Each target boundary is corrected separately; corrections accumulate farther down the hierarchy.": ["각 대상 경계를 따로 보정하므로, 더 아래 단계에는 보정이 누적됩니다.", "各対象の境界を個別に補正するため、階層の下側ほど補正が累積します。"],
    "Enter a finite number between -1000000 and 1000000.": ["-1000000~1000000 사이의 유효한 숫자를 입력하세요.", "-1000000から1000000の範囲で有限の数値を入力してください。"],
    "Scale must be a finite nonzero number between -1000000 and 1000000.": ["배율은 -1000000~1000000 사이에서 0을 제외한 유효한 숫자여야 합니다.", "倍率には-1000000から1000000の範囲で0以外の有限の数値を入力してください。"],
    "A shader texture could not be loaded.": ["셰이더 텍스처를 불러오지 못했습니다.", "シェーダーテクスチャを読み込めませんでした。"],
    "Auxiliary shader texture loading is unavailable.": ["추가 셰이더 텍스처를 불러올 수 없습니다.", "補助シェーダーテクスチャを読み込めません。"],
})
_VIEWER_TRANSLATIONS.update({
    "Rina face": ["리나 얼굴", "璃奈の顔"],
    "Rina board": ["리나 보드", "璃奈ちゃんボード"],
    "Normal face": ["일반 얼굴", "素顔"],
    "Changing the face style reloads the model.": ["얼굴 표시를 바꾸면 모델을 다시 불러옵니다.", "顔の表示を変えるとモデルを読み込み直します。"],
    "Face style changed. Press Open model to refresh the preview.": ["얼굴 표시가 바뀌었습니다. 모델 열기를 눌러 반영하세요.", "顔の表示が変更されました。「モデルを開く」で反映してください。"],
    "The costume variant could not be selected.": ["선택한 의상 버전을 불러오지 못했습니다.", "選択した衣装バージョンを読み込めませんでした。"],
    "Costume variant choices must use selected file numbers.": ["의상 버전은 선택한 파일에서만 고를 수 있습니다.", "衣装バージョンは選択したファイルから指定してください。"],
    "Choose primary or unmasked for the costume variant.": ["의상 버전은 기본 또는 일반 얼굴 중에서 고르세요.", "衣装バージョンは通常版または素顔版を選んでください。"],
    "Conflicting costume variant choices refer to the same file.": ["같은 파일에 서로 다른 의상 버전이 선택됐습니다.", "同じファイルに異なる衣装バージョンが指定されています。"],
    "The costume ZIP declares conflicting costume variants.": ["ZIP의 의상 버전 정보가 서로 충돌합니다.", "ZIP内の衣装バージョン情報が競合しています。"],
    "Choose a valid costume variant.": ["올바른 의상 버전을 선택하세요.", "有効な衣装バージョンを選んでください。"],
    "Costume variant choices must refer to selected costume ZIPs.": ["선택한 의상 ZIP의 버전만 고를 수 있습니다.", "選択した衣装ZIPのバージョンのみ指定できます。"],
    "This costume ZIP does not offer that variant.": ["이 ZIP에는 해당 의상 버전이 없습니다.", "このZIPには指定された衣装バージョンがありません。"],
})
_VIEWER_TRANSLATIONS.update({'Save body edits': ['체형 편집 저장', '体型編集を保存'],
 'Save a new costume copy and an edit recipe. Your original files stay unchanged.': ['수정한 의상 사본과 편집 기록을 '
                                                                                     '저장합니다. 원본 파일은 유지됩니다.',
                                                                                     '編集した衣装のコピーと編集レシピを保存します。元ファイルは保持されます。'],
 'Save edited copy': ['수정본 저장', '編集コピーを保存'],
 'Load edit recipe': ['편집 기록 불러오기', '編集レシピを開く'],
 'Open saved result': ['저장 결과 확인', '保存結果を確認'],
 'Re-edit from original': ['원본에서 계속 편집', '元ファイルから編集を続ける'],
 'Save method and motion check': ['저장 방식·모션 확인', '保存方法・モーション確認'],
 'Selected bone save method': ['선택한 본의 저장 방식', '選択ボーンの保存方法'],
 'Automatic recommendation': ['자동 추천', '自動おすすめ'],
 'Node scaling': ['노드 배율', 'ノード倍率'],
 'Bake into mesh': ['메시에 반영', 'メッシュに反映'],
 'Preview evaluation': ['미리보기 적용 순서', 'プレビューの適用順序'],
 'Editing view': ['편집 결과 보기', '編集結果を表示'],
 'Check node edits against motion': ['모션의 노드 덮어쓰기 확인', 'モーションによるノード上書きを確認'],
 'Preview edits stay temporary until you save a new copy.': ['새 사본을 저장하기 전까지 편집은 미리보기에만 적용됩니다.',
                                                             '新しいコピーを保存するまで、編集はプレビューのみに適用されます。'],
 'Open a model to save body edits.': ['모델을 열면 체형 편집을 저장할 수 있습니다.', 'モデルを開くと体型編集を保存できます。'],
 'Body saving is unavailable for this model.': ['이 모델은 체형 편집을 저장할 수 없습니다.', 'このモデルでは体型編集を保存できません。'],
 'Body changes': ['체형 변경', '体型の変更'],
 'Selected bone': ['선택한 본', '選択中のボーン'],
 'Choose a bone in Individual bones to set its save method.': ['개별 본에서 본을 선택하면 저장 방식을 지정할 수 있습니다.',
                                                               '個別ボーンでボーンを選ぶと、保存方法を設定できます。'],
 'Recommended': ['추천', 'おすすめ'],
 'observed_mv_scale_track': ['확인한 MV에서 배율 키가 있는 본', '調査したMVに倍率トラックがあるボーン'],
 'saved_node_setting': ['파일에 저장된 노드 설정 사용', 'ファイルに保存されたノード設定を使用'],
 'unverified_motion_coverage': ['모션 적용 여부 미확인', 'モーションへの適用は未確認'],
 'The current scale will be saved into the mesh, including existing node scaling.': ['기존 노드 배율을 포함한 현재 배율을 '
                                                                                     '메시에 반영합니다.',
                                                                                     '既存のノード倍率を含む現在の倍率をメッシュに反映します。'],
 'Checks loaded motion tracks against node edits. Open the saved result to inspect mesh changes.': ['불러온 모션이 '
                                                                                                    '노드 편집을 '
                                                                                                    '덮어쓰는지 '
                                                                                                    '확인합니다. '
                                                                                                    '메시 반영 '
                                                                                                    '결과는 저장 '
                                                                                                    '후 다시 열어 '
                                                                                                    '확인하세요.',
                                                                                                    '読み込んだモーションがノード編集を上書きするか確認します。メッシュへの反映結果は保存後に開いて確認してください。'],
 'Editing values are shown after motion. They may differ from game playback.': ['모션 뒤에 편집값을 적용해 보여 줍니다. 게임 '
                                                                                '재생 결과와 다를 수 있습니다.',
                                                                                'モーションの後に編集値を適用して表示します。ゲーム内の再生結果と異なる場合があります。'],
 'Loaded motion scale targets': ['모션의 배율 적용 본', 'モーションの倍率対象ボーン'],
 'No motion is selected.': ['선택한 모션이 없습니다.', 'モーションが選択されていません。'],
 "The recipe's saved child-compensation baseline is retained.": ['편집 기록의 하위 본 보정 기준을 유지합니다.',
                                                                 '編集レシピの子ボーン補正基準を保持しています。'],
 'Reviewing the saved copy. Re-edit from original to continue.': ['저장한 사본을 확인 중입니다. 계속 수정하려면 원본에서 계속 편집을 '
                                                                  '누르세요.',
                                                                  '保存コピーを確認中です。編集を続けるには「元ファイルから編集を続ける」を押してください。'],
 'The body edits could not be saved.': ['체형 편집을 저장하지 못했습니다.', '体型編集を保存できませんでした。'],
 'Saving cancelled.': ['저장을 취소했습니다.', '保存をキャンセルしました。'],
 'Save progress is unavailable. Reopen this page and try again.': ['저장 진행 상황을 연결할 수 없습니다. 이 화면을 다시 열어 시도하세요.',
                                                                   '保存状況に接続できません。この画面を開き直して再度お試しください。'],
 'The save response is invalid.': ['저장 응답이 올바르지 않습니다.', '保存の応答が無効です。'],
 'Reconnecting to save progress…': ['저장 진행 상황에 다시 연결 중…', '保存状況に再接続中…'],
 'Save progress was interrupted. Your original files are unchanged.': ['저장 진행 연결이 끊어졌습니다. 원본 파일은 유지됩니다.',
                                                                       '保存状況の接続が切れました。元ファイルは変更されていません。'],
 'Open the original model before saving body edits.': ['원본 모델을 열고 체형 편집을 저장하세요.',
                                                       '元のモデルを開いてから体型編集を保存してください。'],
 'Change a body value before saving.': ['체형 값을 바꾼 뒤 저장하세요.', '体型の値を変更してから保存してください。'],
 'Saving a new costume copy…': ['새 의상 사본 저장 중…', '新しい衣装コピーを保存中…'],
 'The save result is unavailable.': ['저장 결과를 가져오지 못했습니다.', '保存結果を取得できませんでした。'],
 'Saved. Open the saved result to verify it.': ['저장했습니다. 저장 결과 확인을 눌러 다시 열어 보세요.',
                                                '保存しました。「保存結果を確認」で開き直して確認してください。'],
 'Saved the previous model. The current preview was not changed.': ['이전 모델을 저장했습니다. 현재 미리보기는 유지됩니다.',
                                                                    '前のモデルを保存しました。現在のプレビューは変更されていません。'],
 'Choose a saved body edit recipe JSON file.': ['저장한 체형 편집 기록 JSON 파일을 선택하세요.',
                                                '保存した体型編集レシピのJSONファイルを選択してください。'],
 'The edit recipe could not be opened.': ['편집 기록을 열지 못했습니다.', '編集レシピを開けませんでした。'],
 'The edit recipe is too large or empty.': ['편집 기록 파일이 너무 크거나 비어 있습니다.', '編集レシピのファイルが大きすぎるか空です。'],
 'The body edit recipe is invalid.': ['체형 편집 기록이 올바르지 않습니다.', '体型編集レシピが無効です。'],
 'Open the original model before loading its recipe.': ['원본 모델을 연 뒤 편집 기록을 불러오세요.',
                                                        '元のモデルを開いてから編集レシピを読み込んでください。'],
 'The model changed while its recipe was loading. Try again.': ['편집 기록을 불러오는 동안 모델이 바뀌었습니다. 다시 시도하세요.',
                                                                '編集レシピの読み込み中にモデルが変わりました。再度お試しください。'],
 'Edit recipe restored from the original model.': ['원본 모델에 편집 기록을 불러왔습니다.', '元のモデルに編集レシピを復元しました。'],
 'Loading edit recipe…': ['편집 기록 불러오는 중…', '編集レシピを読み込み中…'],
 'The saved model could not be opened.': ['저장한 모델을 열지 못했습니다.', '保存したモデルを開けませんでした。'],
 'Opening the original model and edit recipe…': ['원본 모델과 편집 기록 여는 중…', '元のモデルと編集レシピを開いています…'],
 'The original model could not be opened.': ['원본 모델을 열지 못했습니다.', '元のモデルを開けませんでした。'],
 'Reset expression edits before saving body changes.': ['체형 변경을 저장하려면 표정 편집을 먼저 초기화하세요.',
                                                        '体型変更を保存する前に表情編集をリセットしてください。'],
 'Reset part visibility changes before saving body changes.': ['체형 변경을 저장하려면 부분 표시 변경을 먼저 초기화하세요.',
                                                               '体型変更を保存する前にパーツ表示の変更をリセットしてください。'],
 'Correct the invalid editing values before saving.': ['잘못 입력한 편집 값을 수정한 뒤 저장하세요.', '無効な編集値を修正してから保存してください。'],
 'Turn saved file settings on before saving body changes.': ['체형 변경을 저장하려면 파일에 저장된 설정을 켜세요.',
                                                             '体型変更を保存する前にファイルに保存された設定を有効にしてください。'],
 'Unsupported saved settings must be resolved before saving body changes.': ['지원하지 않는 파일 설정을 해결한 뒤 체형 변경을 '
                                                                             '저장하세요.',
                                                                             '未対応の保存設定を解決してから体型変更を保存してください。'],
 'Some edited bones are read-only. Open their original model file to save them.': ['편집한 본 중 읽기 전용 본이 있습니다. '
                                                                                   '해당 본의 원본 모델 파일을 열어 '
                                                                                   '저장하세요.',
                                                                                   '編集したボーンに読み取り専用のものがあります。その元モデルを開いて保存してください。'],
 'Choose a valid body save method.': ['올바른 체형 저장 방식을 선택하세요.', '有効な体型保存方法を選択してください。']})
_VIEWER_TRANSLATIONS.update({'Edit preview': ['편집 미리보기', '編集プレビュー'],
 'Choose a save method': ['저장 방식 선택 필요', '保存方法を選択してください'],
 'Baked results can differ while moving. Open the saved result to check the exported model.': ['움직일 때 메시 반영 '
                                                                                               '결과가 미리보기와 다를 '
                                                                                               '수 있습니다. 저장 '
                                                                                               '결과를 다시 열어 '
                                                                                               '확인하세요.',
                                                                                               '動作中のベイク結果はプレビューと異なる場合があります。保存結果を開いて出力モデルを確認してください。'],
 'Choose a save method for unverified body nodes in advanced settings.': ['확인되지 않은 본은 고급 설정에서 저장 방식을 선택하세요.',
                                                                          '未確認のボーンは詳細設定で保存方法を選択してください。'],
 "Edit an attached model's original position in its own source model file.": ['자동 연결된 모델의 위치는 해당 원본 모델 파일에서 '
                                                                              '편집하세요.',
                                                                              '自動接続されたモデルの位置は、その元モデルファイルで編集してください。'],
 'The body editing session is invalid. Open the model again.': ['체형 편집 세션이 올바르지 않습니다. 모델을 다시 여세요.',
                                                                '体型編集セッションが無効です。モデルを開き直してください。'],
 'The body editing session expired. Open the original model again.': ['체형 편집 세션이 만료됐습니다. 원본 모델을 다시 여세요.',
                                                                      '体型編集セッションが期限切れです。元のモデルを開き直してください。'],
 'An original model changed after opening. Reopen it before saving.': ['모델을 연 뒤 원본 파일이 바뀌었습니다. 다시 연 후 저장하세요.',
                                                                       'モデルを開いた後に元ファイルが変更されました。開き直してから保存してください。'],
 'This recipe belongs to different original model bytes. Open its preserved originals first.': ['이 편집 기록의 '
                                                                                                '원본과 현재 모델이 '
                                                                                                '다릅니다. 기록과 '
                                                                                                '함께 보존된 원본을 '
                                                                                                '먼저 여세요.',
                                                                                                'この編集レシピの元データと現在のモデルが異なります。レシピとともに保存された元ファイルを先に開いてください。'],
 'This model has no writable saved NodeScaling component; choose mesh baking.': ['이 모델에는 수정할 수 있는 노드 배율 설정이 '
                                                                                 '없습니다. 메시 반영을 선택하세요.',
                                                                                 'このモデルには編集可能なノード倍率設定がありません。メッシュへの反映を選択してください。'],
 'Child compensation requires a mesh scale edit.': ['하위 본 보정은 메시 배율 편집에서 사용할 수 있습니다.',
                                                    '子ボーン補正はメッシュの倍率編集で使用できます。'],
 'This model has no editable rig.': ['이 모델에는 편집할 수 있는 본이 없습니다.', 'このモデルには編集可能なボーンがありません。'],
 'No original writable body nodes were found.': ['수정할 수 있는 원본 체형 본을 찾지 못했습니다.', '編集可能な元の体型ボーンが見つかりませんでした。'],
 'The selected mesh changes do not influence any writable skinned vertices.': ['선택한 메시 변경이 수정 가능한 정점에 영향을 주지 '
                                                                               '않습니다.',
                                                                               '選択したメッシュ変更は編集可能なスキン頂点に影響しません。']})
_VIEWER_TRANSLATIONS.update({
    "Scale recommendation": ["배율 저장 추천", "倍率の保存おすすめ"],
    "Choose a save method explicitly for position or rotation edits; MV compatibility differs by motion.": ["이동·회전 편집은 저장 방식을 직접 선택하세요. MV 반영 여부는 모션에 따라 다릅니다.", "位置・回転の編集は保存方法を明示的に選択してください。MVへの反映はモーションによって異なります。"],
})
_VIEWER_TRANSLATIONS.update({
    "Save current body changes before opening the saved result.": ["현재 체형 변경을 먼저 저장한 뒤 저장 결과를 여세요.", "現在の体型変更を先に保存してから保存結果を開いてください。"],
})
_VIEWER_TRANSLATIONS.update({'Node Scaling': ['노드 스케일링', 'ノードスケーリング'],
 'Mesh Baker': ['메시 베이커', 'メッシュベイカー'],
 'Motion overwrite check': ['모션 덮어쓰기 확인', 'モーションの上書きを確認'],
 'Recommended for this tool': ['이 도구의 추천 본', 'このツールのおすすめボーン'],
 'New edits here use node settings. Existing edits keep their save method.': ['이 구역의 새 편집은 노드 설정으로 저장합니다. 기존 '
                                                                              '편집의 저장 방식은 유지됩니다.',
                                                                              'このエリアの新しい編集はノード設定として保存します。既存の編集は保存方法を維持します。'],
 'New edits here are baked into a costume copy. Existing edits keep their save method.': ['이 구역의 새 편집은 의상 '
                                                                                          '사본의 메시에 반영합니다. 기존 '
                                                                                          '편집의 저장 방식은 유지됩니다.',
                                                                                          'このエリアの新しい編集は衣装コピーのメッシュに反映します。既存の編集は保存方法を維持します。'],
 'This bone keeps its existing save method when switching tools.': ['구역을 바꿔도 이 본의 기존 저장 방식은 유지됩니다.',
                                                                    'ツールを切り替えても、このボーンの既存の保存方法は維持されます。'],
 'Only body edits are saved. Pose, expression, visibility and camera choices are preview-only.': ['체형 편집만 '
                                                                                                  '저장합니다. '
                                                                                                  '포즈·표정·표시 '
                                                                                                  '여부·카메라는 '
                                                                                                  '미리보기 '
                                                                                                  '설정입니다.',
                                                                                                  '体型編集のみを保存します。姿勢・表情・表示・カメラの選択はプレビュー専用です。']})
_VIEWER_TRANSLATIONS.update({
    "Body editing tools": ["체형 편집 도구", "体型編集ツール"],
    "Node edits": ["노드 편집 수", "ノード編集数"],
    "Mesh edits": ["메시 편집 수", "メッシュ編集数"],
})
_VIEWER_TRANSLATIONS.update({
    "The saved costume variant choices are invalid.": ["저장된 의상 버전 정보가 올바르지 않습니다.", "保存された衣装バージョンの情報が無効です。"],
})
_VIEWER_TRANSLATIONS.update({
    "Mesh baking requires Float32 vertex positions; use saved node settings for this model.": ["메시 반영에는 Float32 정점 위치가 필요합니다. 이 모델은 노드 설정으로 저장하세요.", "メッシュへの反映にはFloat32の頂点位置が必要です。このモデルはノード設定で保存してください。"],
    "Mesh baking requires Float32 vertex normals; use saved node settings for this model.": ["메시 반영에는 Float32 정점 노멀이 필요합니다. 이 모델은 노드 설정으로 저장하세요.", "メッシュへの反映にはFloat32の頂点法線が必要です。このモデルはノード設定で保存してください。"],
    "Mesh baking requires Float32 vertex tangents; use saved node settings for this model.": ["메시 반영에는 Float32 정점 탄젠트가 필요합니다. 이 모델은 노드 설정으로 저장하세요.", "メッシュへの反映にはFloat32の頂点接線が必要です。このモデルはノード設定で保存してください。"],
})
_VIEWER_TRANSLATIONS.update({
    "Show in Finder": ["Finder에서 보기", "Finderで表示"],
    "Adjustment panel width": ["조절 패널 너비", "調整パネルの幅"],
    "The panel width is invalid.": ["조절 패널 너비가 올바르지 않습니다.", "調整パネルの幅が無効です。"],
    "Default panel width": ["기본 너비", "標準の幅"],
    "Reset adjustment panel width": ["조절 패널을 기본 너비로 복원", "調整パネルの幅を標準に戻す"],
    "File panel width": ["파일 선택 영역 너비", "ファイル選択領域の幅"],
    "Default layout": ["기본 배치", "標準レイアウト"],
    "Restore default layout": ["파일·모델·조절 영역을 기본 배치로 복원", "ファイル・モデル・調整の配置を標準に戻す"],
    "Drag to resize. Left and right arrows adjust the width; Home restores the default layout.": ["드래그하여 너비를 바꾸세요. 좌우 화살표로 조절하고 Home 키로 기본 배치를 복원합니다.", "ドラッグして幅を変更できます。左右矢印で調整し、Homeキーで標準配置に戻します。"],
    "Drag to resize files. Left and right arrows adjust the width; Home restores the default layout.": ["드래그하여 파일 선택 영역의 너비를 바꾸세요. 좌우 화살표로 조절하고 Home 키로 기본 배치를 복원합니다.", "ドラッグしてファイル選択領域の幅を変更できます。左右矢印で調整し、Homeキーで標準配置に戻します。"],
    "Drag to resize. Left and right arrows adjust the width; Home restores the default.": ["드래그하여 너비를 바꾸세요. 좌우 화살표로 조절하고 Home 키로 기본 너비를 복원합니다.", "ドラッグして幅を変更できます。左右矢印で調整し、Homeキーで標準の幅に戻します。"],
    "The file selection response is invalid.": ["파일 선택 응답이 올바르지 않습니다.", "ファイル選択の応答が無効です。"],
    "This action is unavailable in this window.": ["이 창에서는 해당 동작을 사용할 수 없습니다.", "このウィンドウではこの操作を利用できません。"],
    "Finish the current native action first.": ["현재 열려 있는 시스템 작업을 먼저 마치세요.", "開いているシステム操作を先に完了してください。"],
    "The native request failed.": ["시스템 작업을 완료하지 못했습니다.", "システム操作を完了できませんでした。"],
    "Choose a saved file to reveal.": ["저장된 파일을 선택하세요.", "保存されたファイルを選択してください。"],
    "Choose a supported language.": ["지원하는 언어를 선택하세요.", "対応している言語を選択してください。"],
    "The native action did not finish. Try again.": ["시스템 작업이 완료되지 않았습니다. 다시 시도하세요.", "システム操作が完了しませんでした。もう一度お試しください。"],
    "This window was closed.": ["창이 닫혔습니다.", "ウィンドウが閉じられました。"],
    "Open at most eight model files at a time.": ["모델 파일은 한 번에 최대 8개까지 열 수 있습니다.", "モデルファイルは一度に8個まで開けます。"],
    "3D graphics are unavailable here. Update your system web view or use a current browser.": ["여기서는 3D 그래픽을 사용할 수 없습니다. 시스템 웹 뷰를 업데이트하거나 최신 브라우저를 사용하세요.", "ここでは3Dグラフィックスを利用できません。システムのWebビューを更新するか、新しいブラウザーを使用してください。"],
})

_VIEWER_TRANSLATIONS.update({
    "Detail body parts": [
        "부위별 세부 조절",
        "部位別の詳細調整"
    ],
    "Recommended detail parts": [
        "추천 세부 부위",
        "推奨する詳細部位"
    ],
    "Choose a detail part": [
        "조절할 세부 부위 선택",
        "調整する部位を選択"
    ],
    "Head and hair": [
        "머리·머리카락",
        "頭・髪"
    ],
    "Upper body and arms": [
        "상체·팔",
        "上半身・腕"
    ],
    "Legs and feet": [
        "다리·발",
        "脚・足"
    ],
    "Other bones": [
        "그 밖의 본",
        "その他のボーン"
    ],
    "Size cards handle hips, breast, skirt, waist and thighs. Other bones remain available in advanced controls.": [
        "엉덩이·가슴·치마·허리·허벅지는 전용 항목에서 조절하세요. 다른 본은 고급 조절에서 선택할 수 있습니다.",
        "ヒップ・胸・スカート・腰・太ももは専用項目で調整できます。他のボーンは詳細設定から選択できます。"
    ],
    "Percent of loaded shape": [
        "불러온 형태 기준 (%)",
        "読み込んだ形状を基準 (%)"
    ],
    "Undo this size adjustment": [
        "이 크기 조절 되돌리기",
        "このサイズ調整を元に戻す"
    ],
    "100% keeps the loaded shape. This adjustment scales the verified HipsSize node, not the pelvis root.": [
        "100%는 불러온 형태입니다. 원본에서 확인된 엉덩이 크기 조절 본(HipsSize)을 사용합니다.",
        "100%は読み込んだ形状です。元モデルで確認されたヒップサイズ用ボーン（HipsSize）を使います。"
    ],
    "100% keeps the loaded shape. Only thickness changes; bone length is preserved.": [
        "100%는 불러온 형태입니다. 본의 길이를 유지하면서 굵기만 바꿉니다.",
        "100%は読み込んだ形状です。ボーンの長さを保ったまま太さだけを変えます。"
    ],
    "Children follow this size adjustment; inverse compensation is not used.": [
        "하위 본도 함께 크기가 바뀝니다. 이 전용 조절 본에는 역보정을 적용하지 않습니다.",
        "子ボーンにもサイズが反映されます。この専用ボーンには逆補正を適用しません。"
    ],
    "Keeps bone length. Spine2 compensation preserves the chest, shoulders and head.": [
        "길이를 유지합니다. Spine2 경계를 보정해 가슴·어깨·머리 크기를 유지합니다.",
        "長さを保ちます。Spine2の境界を補正して胸・肩・頭のサイズを保ちます。"
    ],
    "Keeps bone length. Child compensation preserves the calves and feet.": [
        "길이를 유지합니다. 하위 본을 보정해 종아리·발 크기를 유지합니다.",
        "長さを保ちます。子ボーンを補正してふくらはぎ・足のサイズを保ちます。"
    ],
    "Apply changed axes": [
        "수정한 축 적용",
        "変更した軸を適用"
    ],
    "Actual HipsSize scale values. Apply only the axes you change; other axes stay unchanged.": [
        "현재 모델의 HipsSize 배율입니다. 수정한 축만 적용하며 다른 축은 유지됩니다.",
        "現在のモデルのHipsSizeスケールです。変更した軸だけを適用し、他の軸は維持します。"
    ],
    "Enter a positive finite scale between 0.00000001 and 1000000.": [
        "0.00000001~1000000 사이의 양수 배율을 입력하세요.",
        "0.00000001～1000000の範囲で正の有限スケールを入力してください。"
    ],
    "Enter a percentage between 20 and 250.": [
        "20~250 사이의 비율을 입력하세요.",
        "20～250の範囲で割合を入力してください。"
    ],
    "Resolve conflicting file values before using this control.": [
        "파일의 충돌하는 값을 먼저 해결하세요.",
        "元ファイルの競合する値を先に解決してください。"
    ],
    "This control needs positive original scale values.": [
        "이 항목은 원본 배율이 양수인 경우 사용할 수 있습니다.",
        "この項目には正の元スケール値が必要です。"
    ],
    "Change this bone's save method in advanced controls before using this adjustment.": [
        "고급 조절에서 이 본의 저장 방식을 맞춘 뒤 사용하세요.",
        "詳細設定でこのボーンの保存方法を合わせてから使用してください。"
    ],
    "Reset length-axis edits in advanced controls before adjusting thickness.": [
        "고급 조절에서 길이 축의 수동 편집을 되돌린 뒤 굵기를 조절하세요.",
        "詳細設定で長さ軸の手動編集を元に戻してから太さを調整してください。"
    ],
    "Turn child compensation off in advanced controls before using this node adjustment.": [
        "고급 조절에서 하위 본 보정을 끈 뒤 이 노드 크기를 조절하세요.",
        "詳細設定で子ボーン補正をオフにしてからこのサイズを調整してください。"
    ],
    "This model has no unambiguous nodes for this adjustment.": [
        "이 모델에는 이 항목을 조절할 본이 없거나 중복되어 있습니다.",
        "この項目に必要なボーンがないか、重複しています。"
    ],
    "Child compensation needs mesh baking. Turn it off or choose Mesh Baker.": [
        "하위 본 보정은 메시 베이커용입니다. 보정을 끄거나 저장 방식을 메시 베이커로 바꾸세요.",
        "子ボーン補正にはメッシュベイクが必要です。補正をオフにするか、保存方法をMesh Bakerに変更してください。"
    ],
    "Node Scaling keeps the intended child-bone inheritance; inverse compensation is not used.": [
        "노드 스케일링은 하위 본에 크기를 전달합니다. 역보정은 적용하지 않습니다.",
        "Node Scalingでは子ボーンにサイズを引き継ぎます。逆補正は適用しません。"
    ],
    "Load from game assets": [
        "게임 에셋에서 불러오기",
        "ゲームアセットから読み込む"
    ],
    "Game assets": [
        "게임 에셋",
        "ゲームアセット"
    ],
    "Game region": [
        "게임 버전",
        "ゲーム版"
    ],
    "Global (GL)": [
        "글로벌 (GL)",
        "グローバル (GL)"
    ],
    "Japan (JP)": [
        "일본 (JP)",
        "日本 (JP)"
    ],
    "Character": [
        "캐릭터",
        "キャラクター"
    ],
    "Choose a character": [
        "캐릭터 선택",
        "キャラクターを選択"
    ],
    "Search costumes": [
        "의상 검색",
        "衣装を検索"
    ],
    "Costume": [
        "의상",
        "衣装"
    ],
    "Choose a costume": [
        "의상 선택",
        "衣装を選択"
    ],
    "Costume variant": [
        "의상 종류",
        "衣装の種類"
    ],
    "Default costume": [
        "기본 의상",
        "通常衣装"
    ],
    "Without mask": [
        "마스크 없음",
        "マスクなし"
    ],
    "Download missing assets": [
        "부족한 에셋 다운로드",
        "不足アセットをダウンロード"
    ],
    "Uses downloaded game packs first. Missing assets can be downloaded.": [
        "받아 둔 게임 팩을 먼저 사용합니다. 부족한 에셋은 다운로드할 수 있습니다.",
        "ダウンロード済みゲームパックを優先し、不足分を取得できます。"
    ],
    "Load model": [
        "모델 불러오기",
        "モデルを読み込む"
    ],
    "Use Android bundles": ["Android 번들 사용", "Android版バンドルを使う"],
    "Use iOS bundles": ["iOS 번들 사용", "iOS版バンドルを使う"],
    "Bundle platform": [
        "번들 플랫폼",
        "バンドルのプラットフォーム"
    ],
    "Use this model": [
        "이 모델 사용",
        "このモデルを使用"
    ],
    "Fills this model field with one body bundle. Your 3D preview stays open as it is.": [
        "선택한 본체 번들을 이 모델 칸에 입력합니다. 현재 3D 미리보기는 유지됩니다.",
        "選択した本体バンドルをこのモデル欄に入力します。現在の3Dプレビューはそのままです。"
    ],
    "The selected game asset is not a body bundle.": [
        "선택한 게임 에셋은 코스튬 본체 번들이 아닙니다.",
        "選択したゲームアセットは衣装の本体バンドルではありません。"
    ],
    "Transplanting requires an original UnityFS costume bundle.": [
        "이식에는 원본 UnityFS 코스튬 번들이 필요합니다.",
        "移植には元のUnityFS衣装バンドルが必要です。"
    ],
    "Choose Android or iOS game assets.": [
        "Android 또는 iOS 게임 에셋을 선택하세요.",
        "AndroidまたはiOSのゲームアセットを選択してください。"
    ],
    "The selected costume body does not match its requested native platform.": [
        "선택한 코스튬 본체의 플랫폼이 요청한 플랫폼과 다릅니다.",
        "選択した衣装本体のプラットフォームが要求されたものと一致しません。"
    ],
    "The selected asset is not a skinned costume body for transplanting.": [
        "선택한 에셋은 이식할 수 있는 스킨 메시 코스튬 본체가 아닙니다.",
        "選択したアセットは移植可能なスキンメッシュの衣装本体ではありません。"
    ],
    "The selected costume has no canonical body for that platform.": [
        "이 플랫폼용으로 확인된 코스튬 본체가 없습니다.",
        "このプラットフォーム用の確認済み衣装本体がありません。"
    ],
    "The costume catalog changed. Select the game costume again.": [
        "코스튬 목록이 변경되었습니다. 게임 코스튬을 다시 선택하세요.",
        "衣装一覧が変更されました。ゲームの衣装を選び直してください。"
    ],
    "Native costume body ready for transplanting.": [
        "이식에 사용할 코스튬 본체를 준비했습니다.",
        "移植に使う衣装本体を準備しました。"
    ],
    "Loading costumes…": [
        "의상 목록 불러오는 중…",
        "衣装一覧を読み込み中…"
    ],
    "Preparing game assets…": [
        "게임 에셋 준비 중…",
        "ゲームアセットを準備中…"
    ],
    "No costumes found.": [
        "의상을 찾지 못했습니다.",
        "衣装が見つかりません。"
    ],
    "Game assets are unavailable. Start or prepare the server data first.": [
        "게임 에셋을 사용할 수 없습니다. 서버 데이터를 먼저 준비하세요.",
        "ゲームデータを先に準備してください。"
    ]
})
_VIEWER_TRANSLATIONS["This model cannot save this adjustment with its required method."] = ["이 모델은 이 항목에 필요한 저장 방식을 지원하지 않습니다.", "このモデルは、この項目に必要な保存方法に対応していません。"]
_VIEWER_TRANSLATIONS["The child hierarchy does not match this thickness adjustment. Use advanced controls."] = ["하위 본 구조가 이 굵기 조절과 맞지 않습니다. 고급 조절을 사용하세요.", "子ボーン構造がこの太さ調整に対応していません。詳細設定を使用してください。"]
_VIEWER_TRANSLATIONS["The game model could not be loaded."] = ["게임 모델을 불러오지 못했습니다.", "ゲームモデルを読み込めませんでした。"]
_VIEWER_TRANSLATIONS["The current Node save method does not support child compensation. Use Mesh Baker when compensation is needed."] = ["현재 Node 저장에서는 하위 본 보정을 지원하지 않습니다. 보정이 필요하면 메시 베이커를 사용하세요.", "現在のNode保存では子ボーン補正に対応していません。補正が必要な場合はMesh Bakerを使用してください。"]
_VIEWER_TRANSLATIONS.update({
    "Another game model is being prepared. Try again shortly.": [
        "다른 게임 모델을 준비 중입니다. 잠시 후 다시 시도하세요.",
        "別のゲームモデルを準備中です。少し待って再試行してください。"
    ],
    "Loading the game asset took too long. Try again.": [
        "게임 에셋을 불러오는 데 시간이 오래 걸립니다. 다시 시도하세요.",
        "ゲームアセットの読み込みがタイムアウトしました。再試行してください。"
    ],
    "The game pack is missing. Enable Download missing assets or download the game data first.": [
        "게임 팩이 없습니다. 부족한 에셋 다운로드를 켜거나 게임 데이터를 먼저 받아 주세요.",
        "ゲームパックがありません。不足アセットの取得を有効にするか、先にゲームデータを取得してください。"
    ],
    "The selected costume is no longer available. Refresh the list.": [
        "선택한 의상이 더 이상 없습니다. 목록을 새로 불러오세요.",
        "選択した衣装が見つかりません。一覧を更新してください。"
    ],
    "The selected costume colour assets are unavailable.": [
        "선택한 의상의 색상 에셋을 찾을 수 없습니다.",
        "選択した衣装の色アセットがありません。"
    ],
    "The selected costume colour could not be applied. The base colour was not substituted.": [
        "선택한 의상 색상을 적용하지 못했습니다. 기본 색상으로 대체하지 않았습니다.",
        "選択した衣装の色を適用できませんでした。基本色には置き換えていません。"
    ],
    "This costume has no unmasked model.": [
        "이 의상에는 마스크 없는 모델이 없습니다.",
        "この衣装にはマスクなしモデルがありません。"
    ],
    "This costume is missing from the Android asset catalog.": [
        "이 의상의 Android 에셋 정보가 없습니다.",
        "この衣装のAndroidアセット情報がありません。"
    ],
    "The selected game region is unavailable.": [
        "선택한 게임 버전의 데이터가 없습니다.",
        "選択したゲーム版のデータがありません。"
    ]
})
_VIEWER_TRANSLATIONS.update({
    "Choose source → target": ["원본 체형 → 목표 체형 선택", "元の体型 → 変更先を選択"],
    "Slim": ["가느다란 체형", "細めの体型"],
    "Standard": ["표준 체형", "標準の体型"],
    "Thick": ["굵은 체형", "太めの体型"],
    "Custom adjustment": ["직접 조절한 값", "手動調整値"],
    "Current thigh preset": ["현재 허벅지 프리셋", "現在の太ももプリセット"],
    "Choose the original and target body types. Presets and percentage replace each other; repeated Apply does not compound changes.": [
        "원본 체형과 목표 체형을 직접 선택하세요. 프리셋과 %는 나중에 적용한 값으로 대체되며, 반복 적용해도 누적되지 않습니다.",
        "元の体型と変更先を選択してください。プリセットと%は後から適用した値に置き換わり、繰り返し適用しても累積しません。"
    ],
})
_VIEWER_TRANSLATIONS.update({
    "Mod name": ["모드 이름", "MOD名"],
    "Minimize model": ["모델 최소화", "モデルを最小化"],
    "Show model": ["모델 펼치기", "モデルを表示"],
    "Closing full screen…": ["전체 화면 종료 중…", "全画面表示を終了中…"],
    "Exit full screen before minimizing the model.": ["전체 화면을 종료한 뒤 모델을 최소화하세요.", "全画面表示を終了してからモデルを最小化してください。"],
    "Automatic name": ["자동 이름", "自動の名前"],
    "Automatic": ["자동", "自動"],
    "Position": ["위치", "位置"],
    "Rotation": ["회전", "回転"],
    "The same name is used for the mod ZIP and the game costume. You can edit the suggested name.": [
        "모드 ZIP과 게임 의상에 같은 이름을 사용합니다. 제안된 이름을 직접 바꿀 수 있습니다.",
        "MOD ZIPとゲームの衣装に同じ名前を使います。候補の名前は変更できます。"],
    "Save mod ZIP": ["모드 ZIP 저장", "MOD ZIPを保存"],
    "If one mod ZIP already contains Android and iOS bundles, saving applies the same body edits to both platforms. A single bundle keeps its original platform. Saving does not convert between Android and iOS.": [
        "하나의 모드 ZIP에 Android와 iOS 번들이 이미 함께 들어 있으면, 저장할 때 양쪽 플랫폼에 같은 체형 편집을 적용합니다. 단일 번들은 원래 플랫폼을 유지하며, Android와 iOS 사이의 플랫폼 변환은 하지 않습니다.",
        "1つのMOD ZIPにAndroid用とiOS用のバンドルがすでに含まれている場合、保存時に両プラットフォームへ同じ体型編集を適用します。単一のバンドルは元のプラットフォームを維持し、AndroidとiOSの間で変換は行いません。"],
    "Mod ZIP": ["모드 ZIP", "MOD ZIP"],
    "Edited preview copy": ["편집한 미리보기 사본", "編集したプレビュー用コピー"],
    "Edit recipe": ["편집 기록", "編集レシピ"],
    "Saved in folder": ["저장 폴더", "保存フォルダー"],
    "The Mod ZIP folder cannot be a symbolic link.": ["모드 ZIP 폴더는 심볼릭 링크일 수 없습니다.", "MOD ZIPフォルダーはシンボリックリンクにできません。"],
    "The Mod ZIP folder has too many files with this name. Rename the mod and try again.": ["모드 ZIP 폴더에 같은 이름의 파일이 너무 많습니다. 모드 이름을 바꾼 뒤 다시 시도하세요.", "MOD ZIPフォルダーに同じ名前のファイルが多すぎます。MOD名を変えてもう一度試してください。"],
    "Add to game": ["게임에 추가", "ゲームに追加"],
    "Add to game saves your current body edits as a mod and installs it. Rina's board and unmasked models receive the same body edits.": [
        "게임에 추가를 누르면 현재 체형 편집을 모드로 저장하고 설치합니다. 리나는 보드·보드 없음 모델에 같은 체형 편집을 적용합니다.",
        "「ゲームに追加」は現在の体型編集をMODとして保存してインストールします。璃奈はボードあり・なしのモデルに同じ体型編集を適用します。"],
    "Mod target and Rina variants": ["적용 캐릭터·리나 버전", "対象キャラクター・璃奈のバージョン"],
    "Costume character": ["의상 캐릭터", "衣装のキャラクター"],
    "Edited Rina variant": ["수정한 리나 버전", "編集した璃奈のバージョン"],
    "With Rina board": ["보드 있음", "ボードあり"],
    "Without Rina board": ["보드 없음", "ボードなし"],
    "Other Rina model": ["리나의 다른 버전 모델", "璃奈のもう一方のモデル"],
    "Game assets and paired costume ZIPs are detected automatically. For a separate Rina model, choose its other variant and identify the version you edited.": [
        "게임 에셋과 두 버전이 포함된 의상 ZIP은 자동으로 확인합니다. 별도 리나 모델은 다른 버전 파일과 수정한 버전을 지정하세요.",
        "ゲームアセットと両バージョン入りの衣装ZIPは自動判定します。個別の璃奈モデルでは、もう一方のファイルと編集したバージョンを指定してください。"],
    "Clear": ["지우기", "クリア"],
    "Enter a mod name of 1 to 120 characters.": ["모드 이름을 1~120자로 입력하세요.", "MOD名を1〜120文字で入力してください。"],
    "Saving an installer-ready mod ZIP…": ["설치용 모드 ZIP 저장 중…", "インストール用MOD ZIPを保存中…"],
    "The mod package response is invalid.": ["모드 패키지 응답이 올바르지 않습니다.", "MODパッケージの応答が無効です。"],
    "Mod ZIP saved. You can install it with the mod installer.": ["모드 ZIP을 저장했습니다. 모드 설치기에서 설치할 수 있습니다.", "MOD ZIPを保存しました。MODインストーラーでインストールできます。"],
    "The model, body edits or mod settings changed. Add the current edits to game again.": ["모델·체형 편집 또는 모드 설정이 바뀌었습니다. 현재 편집으로 게임에 추가를 다시 누르세요.", "モデル・体型編集またはMOD設定が変わりました。現在の編集で再度「ゲームに追加」を押してください。"],
    "Adding the costume to game…": ["게임에 의상 추가 중…", "衣装をゲームに追加中…"],
    "Installation progress was interrupted. Check the server console before adding it again.": ["설치 진행 연결이 끊어졌습니다. 다시 추가하기 전에 서버 콘솔을 확인하세요.", "インストール状況への接続が切れました。再度追加する前にサーバーコンソールを確認してください。"],
    "The mod could not be added to game.": ["모드를 게임에 추가하지 못했습니다.", "MODをゲームに追加できませんでした。"],
    "The mod could not be saved.": ["모드를 저장하지 못했습니다.", "MODを保存できませんでした。"],
    "Added to game. Select the new costume in game.": ["게임에 추가했습니다. 게임에서 새 의상을 선택하세요.", "ゲームに追加しました。ゲームで新しい衣装を選んでください。"],
    "Already added to game. Change the edits or mod name to add another copy.": ["이미 게임에 추가했습니다. 다른 사본을 추가하려면 편집값이나 모드 이름을 바꾸세요.", "ゲームに追加済みです。別のコピーを追加するには編集値かMOD名を変更してください。"],
    "Added the saved mod to game. The current preview was not changed.": ["저장한 모드를 게임에 추가했습니다. 현재 미리보기는 유지됩니다.", "保存したMODをゲームに追加しました。現在のプレビューは変更していません。"],
    "Enter a Mod name between 1 and 120 characters without line breaks.": ["모드 이름은 줄바꿈 없이 1~120자로 입력하세요.", "MOD名は改行なしで1〜120文字にしてください。"],
    "Choose a valid character for the Mod ZIP.": ["모드 ZIP에 적용할 캐릭터를 선택하세요.", "MOD ZIPの対象キャラクターを選んでください。"],
    "Choose a valid Rina counterpart file.": ["리나의 다른 버전 모델 파일을 선택하세요.", "璃奈のもう一方のモデルファイルを選んでください。"],
    "Choose which Rina variant is being edited.": ["수정한 리나 버전을 선택하세요.", "編集した璃奈のバージョンを選んでください。"],
    "Choose whether the edited Rina model uses the board.": ["수정한 리나 모델의 보드 유무를 선택하세요.", "編集した璃奈モデルのボードの有無を選んでください。"],
    "Choose the other Rina model file, or keep automatic variant selection.": ["리나의 다른 버전 모델을 선택하거나 버전을 자동으로 두세요.", "璃奈のもう一方のモデルを選ぶか、バージョンを自動にしてください。"],
    "Another Mod ZIP is being prepared. Try again shortly.": ["다른 모드 ZIP을 준비 중입니다. 잠시 후 다시 시도하세요.", "別のMOD ZIPを準備中です。しばらくしてから再度お試しください。"],
    "Mod packaging was cancelled.": ["모드 패키지 생성을 취소했습니다.", "MODのパッケージ作成をキャンセルしました。"],
    "Create a Mod ZIP before adding it to the game.": ["모드 ZIP을 만든 뒤 게임에 추가하세요.", "MOD ZIPを作成してからゲームに追加してください。"],
    "The Mod ZIP installation session expired. Create it again.": ["모드 ZIP 설치 정보가 만료됐습니다. 다시 저장하세요.", "MOD ZIPのインストール情報の期限が切れました。保存し直してください。"],
    "This Mod ZIP is already being added or has been installed. Create a new copy to add it again.": ["이 모드 ZIP은 추가 중이거나 설치를 마쳤습니다. 다시 추가하려면 새 사본을 저장하세요.", "このMOD ZIPは追加中か、すでにインストール済みです。再度追加するには新しいコピーを保存してください。"],
    "The Mod ZIP changed after saving. Create it again before adding it.": ["저장한 모드 ZIP이 바뀌었습니다. 다시 저장한 뒤 추가하세요.", "保存後にMOD ZIPが変わりました。保存し直してから追加してください。"],
    "The saved Mod ZIP is missing or invalid. Create it again.": ["저장한 모드 ZIP이 없거나 올바르지 않습니다. 다시 저장하세요.", "保存したMOD ZIPが見つからないか無効です。保存し直してください。"],
    "The saved Mod ZIP changed while reading. Create it again.": ["읽는 동안 모드 ZIP이 바뀌었습니다. 다시 저장하세요.", "読み込み中にMOD ZIPが変わりました。保存し直してください。"],
    "Prepare the Elichika server data before adding a costume.": ["Elichika 서버 데이터를 준비한 뒤 의상을 추가하세요.", "Elichikaのサーバーデータを準備してから衣装を追加してください。"],
    "The Mod ZIP failed its completed-output check.": ["완성된 모드 ZIP을 검증하지 못했습니다.", "完成したMOD ZIPの検証に失敗しました。"],
    "The costume installation folder cannot be a symbolic link.": ["의상 설치 폴더로 심볼릭 링크를 사용할 수 없습니다.", "衣装のインストール先にシンボリックリンクは使用できません。"],
    "The install copy does not match the saved Mod ZIP.": ["설치 사본이 저장한 모드 ZIP과 일치하지 않습니다.", "インストール用コピーが保存したMOD ZIPと一致しません。"],
    "Costume installation was cancelled. Check the server console before restarting.": ["의상 설치를 취소했습니다. 재시작하기 전에 서버 콘솔을 확인하세요.", "衣装のインストールをキャンセルしました。再起動前にサーバーコンソールを確認してください。"],
    "The Mod ZIP exceeds the size limit.": ["모드 ZIP이 크기 제한을 초과했습니다.", "MOD ZIPがサイズ制限を超えています。"],
    "Choose one Rina costume before creating its paired Mod ZIP.": ["리나 의상 하나를 선택한 뒤 두 버전 모드 ZIP을 저장하세요.", "璃奈の衣装を1つ選んでから両バージョンのMOD ZIPを保存してください。"],
    "Use a complete paired Rina ZIP, or open the original extracted game costume.": ["리나 두 버전이 포함된 ZIP이나 게임에서 추출한 원본 의상을 여세요.", "璃奈の両バージョン入りZIPか、ゲームから抽出した元の衣装を開いてください。"],
    "A copy of the selected costume cannot replace its missing Rina counterpart.": ["선택한 의상의 복사본을 다른 리나 버전 대신 사용할 수 없습니다.", "選択した衣装のコピーを璃奈のもう一方のバージョンの代わりには使えません。"],
    "An explicit Rina counterpart requires a selected Rina costume.": ["리나 의상을 선택했을 때만 다른 버전 모델을 지정할 수 있습니다.", "璃奈の衣装を選択した場合のみ、もう一方のモデルを指定できます。"],
    "Choose a counterpart file and declare which variant is being edited.": ["다른 버전 모델 파일과 수정한 버전을 지정하세요.", "もう一方のモデルファイルと編集したバージョンを指定してください。"],
    "Choose a distinct Rina counterpart for the same platform.": ["같은 플랫폼의 다른 리나 버전 모델을 선택하세요.", "同じプラットフォームの璃奈のもう一方のモデルを選んでください。"],
    "Rina needs both variants. Import this costume from Game assets, open a complete paired Mod ZIP, or explicitly choose its counterpart and variant.": ["리나는 두 버전이 모두 필요합니다. 게임 에셋에서 불러오거나 두 버전이 포함된 모드 ZIP을 여세요. 별도 파일은 다른 버전 모델과 수정한 버전을 지정하세요.", "璃奈は両バージョンが必要です。ゲームアセットから読み込むか、両バージョン入りMOD ZIPを開いてください。個別ファイルではもう一方のモデルと編集したバージョンを指定してください。"],
    "The game catalog does not provide a matching Rina counterpart.": ["게임 목록에서 일치하는 리나의 다른 버전을 찾지 못했습니다.", "ゲームの一覧に対応する璃奈のもう一方のバージョンがありません。"],
    "The game counterpart has a different or unverified platform.": ["다른 버전 모델의 플랫폼이 다르거나 확인되지 않았습니다.", "もう一方のモデルのプラットフォームが異なるか確認できません。"],
    "The Rina counterparts must use the same character and platform.": ["리나의 두 버전은 캐릭터와 플랫폼이 같아야 합니다.", "璃奈の両バージョンは同じキャラクターとプラットフォームである必要があります。"],
    "The Rina ZIP must include both board and unmasked models.": ["리나 ZIP에는 보드 있음·없음 모델이 모두 필요합니다.", "璃奈のZIPにはボードあり・なしのモデルが必要です。"],
})
from webtools.core.viewer_motion_i18n import STRINGS as _MOTION_TRANSLATIONS
_VIEWER_TRANSLATIONS.update(_MOTION_TRANSLATIONS)
_VIEWER_TRANSLATIONS.update({
    "Decode model preview": ["모델 미리보기 해석", "モデルプレビューの解析"],
    "Prepare model materials": ["모델 재질 준비", "モデルマテリアルの準備"],
    "Restore model editing state": ["모델 편집 상태 복원", "モデル編集状態の復元"],
    "The model preparation response is empty or invalid.": ["모델 준비 응답이 비어 있거나 올바르지 않습니다.", "モデルの準備応答が空か無効です。"],
    "Open a model before adding motion.": ["모션을 추가하기 전에 모델을 여세요.", "モーションを追加する前にモデルを開いてください。"],
    "Wait for model saving to finish.": ["모델 저장이 끝날 때까지 기다려 주세요.", "モデルの保存が終わるまでお待ちください。"],
    "Save mesh edits before adding motion.": ["메시 편집을 저장한 뒤 모션을 추가하세요.", "メッシュ編集を保存してからモーションを追加してください。"],
    "Save from the mesh panel to include all current edits.": ["현재 변경을 모두 저장하려면 메시 편집 칸의 저장 버튼을 사용하세요.", "すべての変更を保存するにはメッシュ編集パネルの保存ボタンを使ってください。"],
    "The motion could not be loaded.": ["모션을 불러오지 못했습니다.", "モーションを読み込めませんでした。"],
})

_VIEWER_TRANSLATIONS.update({
    "Clear imported motions": ["불러온 모션 목록 비우기", "読み込んだモーション一覧をクリア"],
    "Model files": ["모델 파일", "モデルファイル"],
    "Imported motion files": ["불러온 모션 파일", "読み込んだモーションファイル"],
    "Costume thumbnail": ["의상 썸네일", "衣装サムネイル"],
    "Texture thumbnail": ["텍스처 썸네일", "テクスチャサムネイル"],
    "Automatic high-quality 3D": ["고품질 3D 자동 생성", "高品質3Dで自動生成"],
    "Rendering costume thumbnail…": ["의상 썸네일을 렌더링하고 있습니다…", "衣装サムネイルをレンダリング中…"],
    "Automatic 3D thumbnail ready.": ["고품질 3D 썸네일을 생성했습니다.", "高品質3Dサムネイルを生成しました。"],
    "The automatic 3D thumbnail renderer is unavailable.": ["고품질 3D 썸네일 렌더러를 사용할 수 없습니다.", "高品質3Dサムネイルレンダラーを使用できません。"],
    "Automatically render the SDK costume camera and member-colored template when packing.": ["패킹할 때 SDK 의상 카메라와 멤버 색상 템플릿으로 자동 렌더링합니다.", "パック時にSDKの衣装カメラとメンバーカラーのテンプレートで自動レンダリングします。"],
    "Choose bundle files": ["파일 여러 개 선택", "ファイルを複数選択"],
    "Add files": ["파일 추가", "ファイルを追加"],
    "Replace existing Mod thumbnail": ["기존 모드의 3D 썸네일 교체", "既存Modの3Dサムネイル置換"],
    "Create new copies of costume Mod ZIPs with automatic high-quality 3D thumbnails, preserving their models and other settings.": ["기존 의상 모드 ZIP의 모델과 설정을 유지하고, 고품질 3D 썸네일을 적용한 새 사본을 만듭니다.", "既存衣装Mod ZIPのモデルと設定を保持し、高品質3Dサムネイルを適用した新しいコピーを作成します。"],
    "Input costume Mod ZIP": ["입력 의상 모드 ZIP", "入力衣装Mod ZIP"],
    "An existing costume Mod ZIP; the original remains unchanged.": ["기존 의상 모드 ZIP을 선택하세요. 원본은 변경하지 않습니다.", "既存の衣装Mod ZIPを選択します。元のファイルは変更しません。"],
    "New costume ZIP copies are saved here; existing files are never overwritten.": ["새 의상 ZIP 사본을 저장할 폴더입니다. 기존 파일은 덮어쓰지 않습니다.", "新しい衣装ZIPコピーの保存先です。既存ファイルは上書きしません。"],
    "Thumbnail costume variant": ["썸네일에 사용할 의상", "サムネイルに使う衣装"],
    "Use Mod default variant": ["모드의 기본 의상 사용", "Modの既定衣装を使用"],
    "Primary costume": ["기본 의상", "基本衣装"],
    "Rina unmasked costume": ["리나 보드 없는 의상", "璃奈ボードなしの衣装"],
    "Selected files: {count}": ["선택한 파일: {count}개", "選択ファイル: {count}個"],
    "Add selected files ({count})": ["선택한 파일 추가 ({count}개)", "選択ファイルを追加（{count}個）"],
    "Select files in this folder": ["현재 폴더 파일 선택", "このフォルダーのファイルを選択"],
    "Deselect files in this folder": ["현재 폴더 선택 해제", "このフォルダーの選択を解除"],
    "Clear selection": ["선택 해제", "選択を解除"],
    "Select file": ["파일 선택", "ファイルを選択"],
    "You can select up to 128 files at once.": ["한 번에 최대 128개 파일을 선택할 수 있습니다.", "一度に選択できるファイルは128個までです。"],
    "Open the selected model before adding motion.": ["선택한 모델을 먼저 연 뒤 모션을 추가하세요.", "選択したモデルを開いてからモーションを追加してください。"],
    "Imported motions are kept when opening another model.": ["다른 모델을 열어도 불러온 모션 목록을 유지합니다.", "別のモデルを開いても読み込んだモーション一覧を保持します。"],
    "The motion library is full. Clear imported motions before adding more.": ["모션 목록이 가득 찼습니다. 불러온 모션 목록을 비운 뒤 추가하세요.", "モーション一覧がいっぱいです。読み込んだモーションをクリアしてから追加してください。"],
    "Gaze": ["시선", "視線"],
    "Gaze control": ["시선 제어", "視線の制御"],
    "Follow motion gaze": ["모션 시선 따르기", "モーションの視線に従う"],
    "Look at the preview camera": ["미리보기 카메라 보기", "プレビューカメラを見る"],
    "Look straight ahead": ["정면 보기", "正面を見る"],
    "Adjust gaze direction": ["시선 방향 조절", "視線の方向を調整"],
    "Horizontal gaze": ["좌우 시선", "左右の視線"],
    "Vertical gaze": ["상하 시선", "上下の視線"],
    "Gaze strength": ["시선 강도", "視線の強さ"],
    "Enter a gaze value within the displayed range.": ["표시된 범위 안의 시선 값을 입력하세요.", "表示範囲内の視線の値を入力してください。"],
    "Open the original face and its eye-pose animation bank to adjust gaze.": ["시선을 조절하려면 원본 얼굴과 눈 포즈 모션을 불러오세요.", "視線を調整するには元の顔と目のポーズアニメーションを読み込んでください。"],
    "The original gaze target is unavailable in this preview.": ["이 미리보기에는 원본 시선 대상이 없습니다.", "このプレビューには元の視線対象がありません。"],
    "Gaze uses the original eye poses without changing eyelids or mouth shapes.": ["원본 눈 포즈로 시선을 조절하며 눈꺼풀·입 모양은 유지합니다.", "元の目のポーズで視線を調整し、まぶたと口の形を保ちます。"],
    "Some original gaze poses are ambiguous for this model.": ["일부 원본 시선 포즈를 구분할 수 없습니다.", "一部の元の視線ポーズを区別できません。"],
    "Some original gaze poses are unavailable for this model.": ["이 모델에서 일부 원본 시선 포즈를 사용할 수 없습니다.", "このモデルでは一部の元の視線ポーズを使用できません。"],
    "An original gaze target is unavailable in this single-model preview.": ["단일 모델 미리보기에는 일부 원본 시선 대상이 없습니다.", "単一モデルのプレビューには一部の元の視線対象がありません。"],
})

_VIEWER_TRANSLATIONS.update({
    "UV line color": ["UV 선 색상", "UV線の色"],
    "Reimport must be on or off.": ["Reimport는 켜기 또는 끄기로 지정하세요.", "Reimportはオンまたはオフで指定してください。"],
    "Reimport": ["원본 다시 불러오기 (Reimport)", "元データを再読み込み (Reimport)"],
    "Read the source again and rebuild the preview without reusing prepared data.": ["원본 파일을 다시 읽고 준비 캐시를 재사용하지 않고 미리보기를 만듭니다.", "元ファイルを読み直し、準備済みキャッシュを使わずにプレビューを作成します。"],
})

for _source, _translated in _VIEWER_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _translated[0]
    _TABLES["ja"][_source] = _translated[1]

_VIEWER_ACCESSORY_TRANSLATIONS = {
    "Correct accessory clipping": ["액세서리 클리핑 해제", "アクセサリーのクリップを解消"],
    "Moves overlapping ornaments with the resized body while keeping their shape. Uses the original model for every preview and save.": [
        "몸에 겹친 장식의 모양은 유지하면서 위치를 보정합니다. 미리보기와 저장은 매번 원본 모델을 기준으로 계산합니다.",
        "体に重なる装飾の形を保ちながら位置を補正します。プレビューと保存は毎回元のモデルから計算します。"],
    "Open a model to check accessories.": ["모델을 열면 액세서리를 확인할 수 있습니다.", "モデルを開くとアクセサリーを確認できます。"],
    "Accessory correction is off.": ["액세서리 보정이 꺼져 있습니다.", "アクセサリー補正はオフです。"],
    "Accessory correction is unavailable for this model.": ["이 모델은 액세서리 보정을 지원하지 않습니다.", "このモデルではアクセサリー補正を利用できません。"],
    "Checking accessory clipping…": ["액세서리 겹침 확인 중…", "アクセサリーの重なりを確認中…"],
    "Corrected accessory anchors": ["보정한 액세서리", "補正したアクセサリー"],
    "Affected anchors": ["보정 대상", "補正対象"],
    "No resized saved body regions were found.": ["보정할 크기 설정이 있는 신체 부위를 찾지 못했습니다.", "補正するサイズ設定のある体の部位が見つかりませんでした。"],
    "No overlapping accessories need correction for these settings.": ["현재 설정에서 보정이 필요한 겹친 액세서리가 없습니다.", "現在の設定では補正が必要な重なるアクセサリーはありません。"],
    "Check accessories again": ["액세서리 다시 확인", "アクセサリーを再確認"],
    "Advanced correction settings": ["보정 고급 설정", "補正の詳細設定"],
    "Correction strength": ["보정 강도", "補正の強さ"],
    "Minimum overlap (0–1)": ["최소 겹침 비율 (0–1)", "最小重なり率 (0–1)"],
    "Also close gaps after shrinking": ["크기를 줄여 생긴 틈도 보정", "縮小で生じた隙間も補正"],
    "Enter a correction strength from 0 to 3 and an overlap from 0 to 1.": ["보정 강도는 0~3, 겹침 비율은 0~1로 입력하세요.", "補正の強さは0〜3、重なり率は0〜1で入力してください。"],
    "The accessory correction settings are invalid.": ["액세서리 보정 설정이 올바르지 않습니다.", "アクセサリー補正の設定が無効です。"],
    "The accessory preview response is invalid.": ["액세서리 미리보기 결과가 올바르지 않습니다.", "アクセサリーのプレビュー結果が無効です。"],
    "Accessory correction could not be checked.": ["액세서리 보정을 확인하지 못했습니다.", "アクセサリー補正を確認できませんでした。"],
    "This model's skinning cannot be checked safely. Turn accessory correction off to save other edits.": [
        "이 모델의 스킨을 안전하게 확인할 수 없습니다. 다른 편집을 저장하려면 액세서리 보정을 끄세요.",
        "このモデルのスキニングを安全に確認できません。他の編集を保存するにはアクセサリー補正をオフにしてください。"],
    "Wait for the accessory check before saving.": ["액세서리 확인이 끝난 뒤 저장하세요.", "アクセサリーの確認が終わってから保存してください。"],
    "The accessory skin cannot be analyzed safely:": ["액세서리의 본·가중치를 안전하게 분석할 수 없습니다:", "アクセサリーのスキニングを安全に解析できません:"],
    "Reset explicit accessory-anchor position edits before applying automatic unclipping.": ["자동 보정을 적용하려면 장식의 수동 위치 편집을 먼저 초기화하세요.", "自動補正を適用するには、装飾の手動位置編集を先にリセットしてください。"],
    "This model's skinning cannot be checked safely. Turn accessory correction off before saving.": ["이 모델의 본·가중치를 안전하게 확인할 수 없습니다. 저장하려면 액세서리 보정을 끄세요.", "このモデルのスキニングを安全に確認できません。保存するにはアクセサリー補正をオフにしてください。"],
    "The accessory anchor failed its saved-position reload check.": ["저장 후 다시 확인한 액세서리 위치가 요청과 다릅니다.", "保存後に再確認したアクセサリーの位置が要求と一致しません。"],
    "The accessory hierarchy points outside its original model.": ["액세서리의 본 연결이 원본 모델 밖을 가리킵니다.", "アクセサリーのボーン階層が元のモデル外を参照しています。"],
    "An accessory scale region has a singular authored scale.": ["보정할 부위의 원본 배율을 역산할 수 없습니다.", "補正する部位の元のスケールを逆算できません。"],
    "The costume skin is ambiguous; accessory unclipping cannot choose a renderer.": ["의상의 본·가중치가 모호해 보정할 메시를 정할 수 없습니다.", "衣装のスキニングが曖昧なため、補正するメッシュを選べません。"],
    "Accessory unclipping cannot follow external meshes.": ["외부 메시를 참조하는 액세서리는 보정할 수 없습니다.", "外部メッシュを参照するアクセサリーは補正できません。"],
    "Accessory unclipping cannot follow external skin bones.": ["외부 본을 참조하는 액세서리는 보정할 수 없습니다.", "外部スキンボーンを参照するアクセサリーは補正できません。"],
    "The accessory skin is not bound to its original model.": ["액세서리의 본·가중치가 원본 모델과 연결되어 있지 않습니다.", "アクセサリーのスキニングが元のモデルに結び付いていません。"],
    "The accessory skin has inconsistent bind poses.": ["액세서리의 기준 본 자세가 일치하지 않습니다.", "アクセサリーのバインドポーズが一致しません。"],
    "The accessory skin exceeds the supported vertex limit.": ["액세서리 메시가 지원하는 정점 수를 초과합니다.", "アクセサリーメッシュの頂点数が対応上限を超えています。"],
    "The accessory skin contains invalid vertex data.": ["액세서리 메시의 정점 데이터가 올바르지 않습니다.", "アクセサリーメッシュの頂点データが無効です。"],
    "The accessory skin has unbound or non-normalized vertex weights.": ["액세서리에 연결되지 않았거나 정규화되지 않은 정점 가중치가 있습니다.", "アクセサリーに未設定または正規化されていない頂点ウェイトがあります。"],
    "The accessory skin contains an unbound weighted bone.": ["액세서리 정점의 가중치가 없는 본을 참조합니다.", "アクセサリーの頂点ウェイトが未設定のボーンを参照しています。"],
    "The accessory bind poses contain invalid transforms.": ["액세서리의 기준 본 자세에 올바르지 않은 변환이 있습니다.", "アクセサリーのバインドポーズに無効な変換があります。"],
    "An accessory overlaps multiple equally likely body regions.": ["액세서리가 여러 부위와 비슷하게 겹쳐 보정 대상을 정할 수 없습니다.", "アクセサリーが複数の部位と同程度に重なり、補正対象を選べません。"],
    "The accessory anchor has no unambiguous writable rest position.": ["액세서리의 원본 위치를 안전하게 수정할 수 없습니다.", "アクセサリーの元の位置を安全に編集できません。"],
    "The accessory lift has a singular transform chain.": ["액세서리 보정에 필요한 본 변환을 역산할 수 없습니다.", "アクセサリー補正に必要なボーン変換を逆算できません。"],
    "The accessory lift exceeds its supported numeric range.": ["액세서리 보정값이 지원하는 범위를 벗어납니다.", "アクセサリーの補正値が対応範囲を超えています。"],
}
for _source, _translated in _VIEWER_ACCESSORY_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _translated[0]
    _TABLES["ja"][_source] = _translated[1]

_VIEWER_MODEL_SAVE_TRANSLATIONS = {
    "Fit full character": ["전신에 맞춤", "全身を表示"],
    "Include the whole character. Off keeps the face and upper costume larger.": ["전신을 화면에 맞춥니다. 끄면 얼굴과 의상 상반신을 더 크게 표시합니다.", "全身を画面内に収めます。オフでは顔と衣装の上半身を大きく表示します。"],
    "Rimlight": ["림라이트", "リムライト"],
    "Clip nearby surfaces": ["가까운 표면 잘라내기", "近くの表面をクリップ"],
    "Near clip distance (model units)": ["절단 거리 (모델 단위)", "クリップ距離（モデル単位）"],
    "Hide surfaces closer than this distance to see and select the mesh behind them. Preview only.": ["카메라에서 이 거리보다 가까운 표면을 숨겨 뒤쪽 메시를 보고 선택합니다. 미리보기에만 적용됩니다.", "カメラからこの距離より近い表面を隠し、奥のメッシュを表示・選択します。プレビューのみに適用されます。"],
    "Preview lighting only; saved model materials stay unchanged.": ["미리보기의 조명 설정입니다. 저장하는 모델의 원본 재질 값은 유지됩니다.", "プレビューの照明設定です。保存するモデルの元のマテリアル値は維持されます。"],
    "Choose a real donor file, not a symbolic link.": ["바로가기나 심볼릭 링크 대신 원본 도너 파일을 선택하세요.", "ショートカットやシンボリックリンクではなく、実体のあるドナーファイルを選んでください。"],
    "The donor costume is outside the allowed folders.": ["도너 의상이 앱에서 접근할 수 있는 폴더 밖에 있습니다.", "ドナー衣装がアプリからアクセスできるフォルダの外にあります。"],
    "This costume's body uses the face its ZIP includes, so that face cannot be left out. Tick 'Include face and mouth edits for this costume' to keep it; no Mod ZIP was created.": ["이 의상의 몸체는 ZIP에 포함된 얼굴을 사용하므로 그 얼굴을 뺄 수 없습니다. '이 코스튬의 얼굴·입 편집 포함'을 선택해 얼굴을 유지하세요. 모드 ZIP은 생성하지 않았습니다.", "この衣装の本体はZIPに同梱された顔を使用しているため、その顔を外すことはできません。「この衣装の顔・口の編集を含める」をオンにして顔を残してください。Mod ZIPは作成されていません。"],
    "This costume ZIP includes its own face, so it is included by default. Only this costume uses it; other costumes and the character's shared face stay unchanged.": ["이 의상 ZIP에는 자체 얼굴이 포함되어 있어 기본으로 함께 포함됩니다. 이 얼굴은 이 코스튬만 사용하며, 다른 의상과 캐릭터의 공용 얼굴에는 적용되지 않습니다.", "この衣装のZIPには専用の顔が同梱されているため、初期設定で含めます。この顔はこの衣装だけが使用し、他の衣装やキャラクター共通の顔には適用されません。"],
    "Choose one costume to package; unrelated model files cannot share one Mod ZIP.": ["모드 ZIP으로 묶을 의상을 하나만 선택하세요. 서로 관계없는 모델 파일은 한 모드 ZIP에 함께 넣을 수 없습니다.", "Mod ZIPにまとめる衣装を1つだけ選んでください。関係のないモデルファイルを1つのMod ZIPにまとめることはできません。"],
    "The costume installer stopped with exit code {code}. Usual causes are missing Elichika settings (config.json) or a Mod ZIP the installer could not find in its costume folder; the server console shows the installer's message.": ["의상 설치 프로그램이 종료 코드 {code}로 중단되었습니다. 흔한 원인은 Elichika 설정 파일(config.json)이 없거나 설치 프로그램이 의상 폴더에서 모드 ZIP을 찾지 못한 경우입니다. 설치 프로그램의 메시지는 서버 콘솔에 표시됩니다.", "衣装インストーラーが終了コード {code} で停止しました。よくある原因は、Elichikaの設定ファイル（config.json）がないことや、インストーラーが衣装フォルダでMod ZIPを見つけられなかったことです。インストーラーのメッセージはサーバーのコンソールに表示されます。"],
    "Choose whether to include this costume's verified face companion.": ["이 코스튬에 얼굴·입 편집을 포함할지 선택하세요.", "この衣装に顔・口の編集を含めるか選んでください。"],
    "Open the original model before saving model edits.": ["원본 모델을 열고 모델 편집을 저장하세요.", "元のモデルを開いてからモデル編集を保存してください。"],
    "The model edit recipe is invalid.": ["모델 편집 기록이 올바르지 않습니다.", "モデル編集レシピが無効です。"],
    "Save current model changes before opening the saved result.": ["현재 모델 변경을 먼저 저장한 뒤 저장 결과를 여세요.", "現在のモデルの変更を先に保存してから保存結果を開いてください。"],
    "Save model edits": ["모델 편집 저장", "モデル編集を保存"],
    "Model changes": ["모델 변경", "モデルの変更"],
    "Open a model to save model edits.": ["모델을 열면 편집 내용을 저장할 수 있습니다.", "モデルを開くと編集内容を保存できます。"],
    "Model saving is unavailable for this model.": ["이 모델은 편집 내용을 저장할 수 없습니다.", "このモデルの編集内容は保存できません。"],
    "Save body, mesh, outline and physics edits together with transplanted clothing. Pose, expression, visibility and camera choices are preview-only.": ["이식된 의상과 체형·메시·외곽선·물리 편집을 함께 저장합니다. 포즈·표정·표시 여부·카메라 설정은 미리보기에만 적용됩니다.", "移植した衣装と体型・メッシュ・輪郭線・物理の編集をまとめて保存します。ポーズ・表情・表示・カメラ設定はプレビュー専用です。"],
    "Add to game packages the current model edits and installs a new costume.": ["현재 모델의 편집 내용을 모드로 묶어 새 코스튬으로 설치합니다.", "現在のモデルの編集内容をModにまとめ、新しい衣装としてインストールします。"],
    "Include face and mouth edits for this costume": ["이 코스튬의 얼굴·입 편집 포함", "この衣装の顔・口の編集を含める"],
    "Only this costume uses the included face. Other costumes and the character's shared face stay unchanged.": ["포함한 얼굴은 이 코스튬만 사용합니다. 다른 의상과 캐릭터의 공용 얼굴에는 적용되지 않습니다.", "含めた顔はこの衣装だけが使用します。他の衣装やキャラクター共通の顔には適用されません。"],
    "Face and mouth edits will not be applied in game. This costume uses the game's original face.": ["게임에 얼굴·입 편집을 적용하지 않습니다. 이 코스튬은 게임의 원래 얼굴을 사용합니다.", "ゲームに顔・口の編集を適用しません。この衣装はゲームの元の顔を使用します。"],
    "The game's original face could not be checked on this device. Open the costume once with 'Load from game assets' so it can be checked, or tick this option to include the face and mouth edits.": ["이 기기에서 게임의 원래 얼굴을 확인할 수 없습니다. '게임 에셋에서 불러오기'로 이 코스튬을 한 번 열면 확인할 수 있고, 이 옵션을 선택하면 얼굴·입 편집이 포함됩니다.", "この端末ではゲームの元の顔を確認できません。「ゲームアセットから読み込む」でこの衣装を一度開くと確認できます。このオプションをオンにすると顔・口の編集が含まれます。"],
    "The game's original face could not be checked on this device, so this costume's face cannot be left out yet. Open the costume once with 'Load from game assets' so its face can be checked, or tick 'Include face and mouth edits for this costume' to include the face edits; no Mod ZIP was created.": ["이 기기에서 게임의 원래 얼굴을 확인할 수 없어 아직 이 코스튬의 얼굴을 뺄 수 없습니다. '게임 에셋에서 불러오기'로 이 코스튬을 한 번 열면 얼굴을 확인할 수 있고, '이 코스튬의 얼굴·입 편집 포함'을 선택하면 얼굴 편집이 포함됩니다. 모드 ZIP은 생성하지 않았습니다.", "この端末ではゲームの元の顔を確認できないため、まだこの衣装の顔を外せません。「ゲームアセットから読み込む」でこの衣装を一度開くと顔を確認できます。「この衣装の顔・口の編集を含める」をオンにすると顔の編集が含まれます。Mod ZIPは作成されていません。"],
    "Open the original face with this costume to include face and mouth edits.": ["얼굴·입 편집을 포함하려면 이 의상의 원래 얼굴 파일도 함께 불러오세요.", "顔・口の編集を含めるには、この衣装の元の顔ファイルも一緒に開いてください。"],
    "Choose whether to include face and mouth edits for this costume.": ["이 코스튬의 얼굴·입 편집을 포함할지 선택하세요.", "この衣装の顔・口の編集を含めるか選んでください。"],
    "Apply selected face deletions before saving.": ["칠한 면의 삭제를 적용한 뒤 저장하세요.", "塗った面の削除を適用してから保存してください。"],
    "Vertex positions": ["정점 위치", "頂点の位置"],
    "Skin weights": ["스킨 가중치", "スキンウェイト"],
    "Outlines": ["외곽선", "輪郭線"],
}
for _source, _translated in _VIEWER_MODEL_SAVE_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _translated[0]
    _TABLES["ja"][_source] = _translated[1]

# Costume variant (pair) refusals that name one part: fixed sentences ending in
# ": {name}" (viewer_mod_pair_edits.NAMED_REFUSALS). The viewer translates the
# sentence and keeps the name. Rina board view: held face outline rows.
_VIEWER_PAIR_TRANSLATIONS = {
    "The counterpart is missing a unique matching bone hierarchy: {name}": (
        "다른 버전 모델에 같은 계층의 고유한 본이 없습니다: {name}", "もう一方のモデルに同じ階層の固有のボーンがありません: {name}"),
    "The counterpart bone is not writable: {name}": (
        "다른 버전 모델의 본은 저장할 수 없습니다: {name}", "もう一方のモデルのボーンは保存できません: {name}"),
    "The counterpart cannot preserve the selected save method: {name}": (
        "다른 버전 모델에서는 선택한 저장 방식을 쓸 수 없습니다: {name}", "もう一方のモデルでは選択した保存方法を使えません: {name}"),
    "The counterpart has no unique matching physics component: {name}": (
        "다른 버전 모델에 일치하는 고유한 물리 컴포넌트가 없습니다: {name}", "もう一方のモデルに一致する固有の物理コンポーネントがありません: {name}"),
    "The counterpart has no unique matching outline mesh: {name}": (
        "다른 버전 모델에 일치하는 고유한 외곽선 메시가 없습니다: {name}", "もう一方のモデルに一致する固有の輪郭線メッシュがありません: {name}"),
    "The counterpart has no verified matching vertex order for detailed outline edits: {name}": (
        "다른 버전 모델의 정점 순서가 같은지 확인할 수 없어 정점별 외곽선 편집을 적용할 수 없습니다: {name}",
        "もう一方のモデルの頂点の順序が同じか確認できないため、頂点ごとの輪郭線編集を適用できません: {name}"),
    "Edits of parts that only the selected costume variant has stay on that variant: {names}": (
        "선택한 의상 버전에만 있는 부분의 편집은 그 버전에만 적용됩니다: {names}",
        "選択した衣装バージョンにだけある部分の編集は、そのバージョンにのみ適用されます: {names}"),
    "1 face outline edit made in the Normal face view is kept ({meshes}).": (
        "일반 얼굴 보기에서 편집한 얼굴 외곽선 1개가 유지됩니다 ({meshes}).",
        "素顔の表示で編集した顔の輪郭線1件を保持しています（{meshes}）。"),
    "{count} face outline edits made in the Normal face view are kept ({meshes}).": (
        "일반 얼굴 보기에서 편집한 얼굴 외곽선 {count}개가 유지됩니다 ({meshes}).",
        "素顔の表示で編集した顔の輪郭線{count}件を保持しています（{meshes}）。"),
    "This recipe sets the face outlines itself; 1 face outline edit made in the Normal face view was released.": (
        "이 편집 기록은 얼굴 외곽선을 직접 정하므로, 일반 얼굴 보기에서 편집한 얼굴 외곽선 1개는 유지되지 않습니다.",
        "この編集レシピは顔の輪郭線を指定しているため、素顔の表示で編集した顔の輪郭線1件は保持されません。"),
    "This recipe sets the face outlines itself; {count} face outline edits made in the Normal face view were released.": (
        "이 편집 기록은 얼굴 외곽선을 직접 정하므로, 일반 얼굴 보기에서 편집한 얼굴 외곽선 {count}개는 유지되지 않습니다.",
        "この編集レシピは顔の輪郭線を指定しているため、素顔の表示で編集した顔の輪郭線{count}件は保持されません。"),
    "This recipe edits the face textures itself; 1 face outline edit made in the Normal face view was released.": (
        "이 편집 기록은 얼굴 텍스처를 직접 편집하므로, 일반 얼굴 보기에서 편집한 얼굴 외곽선 1개는 유지되지 않습니다.",
        "この編集レシピは顔のテクスチャを編集しているため、素顔の表示で編集した顔の輪郭線1件は保持されません。"),
    "This recipe edits the face textures itself; {count} face outline edits made in the Normal face view were released.": (
        "이 편집 기록은 얼굴 텍스처를 직접 편집하므로, 일반 얼굴 보기에서 편집한 얼굴 외곽선 {count}개는 유지되지 않습니다.",
        "この編集レシピは顔のテクスチャを編集しているため、素顔の表示で編集した顔の輪郭線{count}件は保持されません。"),
    "This recipe edits the face itself; 1 face outline edit made in the Normal face view was released.": (
        "이 편집 기록은 얼굴을 직접 편집하므로, 일반 얼굴 보기에서 편집한 얼굴 외곽선 1개는 유지되지 않습니다.",
        "この編集レシピは顔そのものを編集しているため、素顔の表示で編集した顔の輪郭線1件は保持されません。"),
    "This recipe edits the face itself; {count} face outline edits made in the Normal face view were released.": (
        "이 편집 기록은 얼굴을 직접 편집하므로, 일반 얼굴 보기에서 편집한 얼굴 외곽선 {count}개는 유지되지 않습니다.",
        "この編集レシピは顔そのものを編集しているため、素顔の表示で編集した顔の輪郭線{count}件は保持されません。"),
    # Separator of a list of part names inside a sentence ({names}, {meshes}).
    ", ": (", ", "、"),
}
for _source, (_korean, _japanese) in _VIEWER_PAIR_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese


# MV Studio editor lane C: the camera editor (keys, curves, key diamonds). "Keyframes",
# "Result" and "Automatic" are already translated above and are not redefined here.
_MV_EDITOR_C_TRANSLATIONS = {
    "Camera editor": ("카메라 편집기", "カメラエディター"),
    "{count} samples · {rate} Hz": ("샘플 {count}개 · {rate} Hz", "サンプル{count}個 · {rate} Hz"),
    "Open camera editor": ("카메라 편집기 열기", "カメラエディターを開く"),
    "Key {time}": ("키 {time}", "キー {time}"),
    "Original motion": ("원본 움직임", "元の動き"),
    "Offset keys": ("오프셋 키", "オフセットキー"),
    "Keyframes (replace)": ("키프레임 (교체)", "キーフレーム（置き換え）"),
    "Camera mode": ("카메라 모드", "カメラモード"),
    "Offset space": ("오프셋 기준", "オフセットの基準"),
    "View-relative": ("시점 기준", "視点基準"),
    "World": ("월드", "ワールド"),
    "Camera keys": ("카메라 키", "カメラキー"),
    "Key current view": ("현재 시점 키 추가", "現在の視点をキー"),
    "Add key": ("키 추가", "キーを追加"),
    "Duplicate key": ("키 복제", "キーを複製"),
    "Delete key": ("키 삭제", "キーを削除"),
    "Previous key": ("이전 키", "前のキー"),
    "Next key": ("다음 키", "次のキー"),
    "Align view to game camera": ("시점을 게임 카메라에 맞추기", "視点をゲームカメラに合わせる"),
    "Revert shot": ("샷 되돌리기", "ショットを元に戻す"),
    "Convert to keyframes": ("키프레임으로 변환", "キーフレームに変換"),
    "Auto key": ("자동 키", "自動キー"),
    "Keys the free camera view every time you finish moving it.": (
        "자유 카메라를 움직일 때마다 그 시점을 키로 저장합니다.", "自由カメラを動かすたびに、その視点をキーにします。"),
    "At the playhead": ("재생 위치 값", "再生位置の値"),
    "Value": ("값", "値"),
    "Offset": ("오프셋", "オフセット"),
    "X": ("X", "X"),
    "Y": ("Y", "Y"),
    "Z": ("Z", "Z"),
    "Pan": ("팬", "パン"),
    "Tilt": ("틸트", "チルト"),
    "Roll": ("롤", "ロール"),
    "FOV": ("화각", "画角"),
    "Truck": ("트럭 (좌우)", "トラック（左右）"),
    "Pedestal": ("페데스탈 (상하)", "ペデスタル（上下）"),
    "Dolly": ("돌리 (앞뒤)", "ドリー（前後）"),
    "Selected key": ("선택한 키", "選択したキー"),
    "Frame": ("프레임", "フレーム"),
    "Interpolation": ("보간", "補間"),
    "Handles": ("핸들", "ハンドル"),
    "Constant": ("상수", "一定"),
    "Linear": ("선형", "リニア"),
    "Bezier": ("베지어", "ベジェ"),
    "Auto clamped": ("자동 클램프", "自動クランプ"),
    "Flat": ("평탄", "フラット"),
    "Free": ("자유", "フリー"),
    "Ease presets": ("이징 프리셋", "イージングプリセット"),
    "Ease in-out": ("이즈 인아웃", "イーズインアウト"),
    "Ease in": ("이즈 인", "イーズイン"),
    "Ease out": ("이즈 아웃", "イーズアウト"),
    "Curve channels": ("커브 채널", "カーブのチャンネル"),
    "Camera curves": ("카메라 커브", "カメラカーブ"),
    "Shot {index} / {count}": ("샷 {index} / {count}", "ショット {index} / {count}"),
    "Frame {frame} / {last}": ("프레임 {frame} / {last}", "フレーム {frame} / {last}"),
    "No camera shot at the playhead.": ("재생 위치에 카메라 샷이 없습니다.", "再生位置にカメラショットがありません。"),
    "New camera shot at playhead": ("재생 위치에 새 카메라 샷", "再生位置に新しいカメラショット"),
    "Camera shot": ("카메라 샷", "カメラショット"),
    "Camera (editor)": ("카메라 (편집기)", "カメラ（エディター）"),
    "This camera shot cannot be edited.": ("이 카메라 샷은 편집할 수 없습니다.", "このカメラショットは編集できません。"),
    "The camera samples of this shot cannot be exported.": (
        "이 샷의 카메라 샘플은 내보낼 수 없습니다.", "このショットのカメラサンプルは書き出せません。"),
    "Switch the preview camera to Free camera to key the view.": (
        "시점을 키로 저장하려면 미리보기 카메라를 자유 카메라로 바꾸세요.",
        "視点をキーにするには、プレビューカメラを自由カメラに切り替えてください。"),
    "A camera rig also moves this shot.": ("카메라 리그도 이 샷을 움직입니다.", "カメラリグもこのショットを動かしています。"),
    "This shot's length is not whole frames (1/60 s): its camera edits cannot be exported until it is.": (
        "이 샷의 길이가 프레임(1/60초) 단위가 아닙니다. 프레임 단위로 맞추기 전에는 카메라 편집을 내보낼 수 없습니다.",
        "このショットの長さがフレーム（1/60秒）単位ではありません。フレーム単位にするまでカメラの編集は書き出せません。"),
    "Set the length of camera shots with camera edits to whole frames (1/60 s) before exporting.": (
        "내보내기 전에 카메라를 편집한 샷의 길이를 프레임(1/60초) 단위로 맞추세요.",
        "書き出す前に、カメラを編集したショットの長さをフレーム（1/60秒）単位にしてください。"),
    "Keys past the end of this shot: {count}. They are hidden but still shape its motion, and come back if the shot is made longer.": (
        "이 샷의 끝 뒤에 있는 키: {count}개. 숨겨져 있지만 움직임에는 계속 반영되며, 샷을 늘리면 다시 나타납니다.",
        "このショットの終わりより後のキー：{count} 個。非表示ですが動きには反映され、ショットを長くすると戻ります。"),
    "Continue: the preview holds this shot's end pose. In the game it may play on if the camera clip is longer than the shot.": (
        "계속: 미리보기는 이 샷의 마지막 포즈를 유지합니다. 카메라 클립이 샷보다 길면 게임에서는 이어서 재생될 수 있습니다.",
        "続ける：プレビューはこのショットの最後のポーズを保ちます。カメラクリップがショットより長いと、ゲームでは再生が続くことがあります。"),
    "The camera could not be baked.": ("카메라를 굽지 못했습니다.", "カメラを焼き込めませんでした。"),
    "Edit camera key": ("카메라 키 편집", "カメラキーを編集"),
    "Add camera key": ("카메라 키 추가", "カメラキーを追加"),
    "Move camera key": ("카메라 키 이동", "カメラキーを移動"),
    "Delete camera key": ("카메라 키 삭제", "カメラキーを削除"),
    "Duplicate camera key": ("카메라 키 복제", "カメラキーを複製"),
    "Edit camera handle": ("카메라 핸들 편집", "カメラハンドルを編集"),
    "Change interpolation": ("보간 변경", "補間を変更"),
    "Change handle type": ("핸들 종류 변경", "ハンドルの種類を変更"),
    "Apply ease preset": ("이징 프리셋 적용", "イージングプリセットを適用"),
    "Change camera mode": ("카메라 모드 변경", "カメラモードを変更"),
    "Change offset space": ("오프셋 기준 변경", "オフセットの基準を変更"),
    "New camera shot": ("새 카메라 샷", "新しいカメラショット"),
    "Remove the camera keys of this shot and play its original motion?": (
        "이 샷의 카메라 키를 지우고 원래 움직임으로 재생할까요?", "このショットのカメラキーを消して、元の動きで再生しますか？"),
    "Replace this shot's motion with keys at its first and last frame and at every key?": (
        "이 샷의 움직임을 첫 프레임, 마지막 프레임과 각 키 위치의 키로 바꿀까요?",
        "このショットの動きを、最初と最後のフレームと各キーの位置のキーに置き換えますか？"),
    "Turn the keys into offsets over the original motion at the same frames?": (
        "같은 프레임에서 키를 원래 움직임에 대한 오프셋으로 바꿀까요?",
        "同じフレームで、キーを元の動きに対するオフセットに変えますか？"),
    # Several keys at once ("Clear selection" is translated above).
    "Keys can be selected in one camera shot at a time.": (
        "키는 한 번에 한 카메라 샷 안에서만 선택할 수 있습니다.", "キーは一度に1つのカメラショットの中でだけ選択できます。"),
    "Key selection": ("키 선택", "キーの選択"),
    "Select all keys": ("모든 키 선택", "すべてのキーを選択"),
    "Copy keys": ("키 복사", "キーをコピー"),
    "Paste keys": ("키 붙여넣기", "キーを貼り付け"),
    "No keys selected": ("선택한 키 없음", "選択したキーはありません"),
    "Keys selected: {count}": ("키 {count}개 선택됨", "{count}個のキーを選択中"),
    "Keys selected in shot {index}: {count}": ("샷 {index}의 키 {count}개 선택됨", "ショット {index} のキーを{count}個選択中"),
    "Time scale (%)": ("간격 배율 (%)", "間隔の倍率 (%)"),
    "Scale timing": ("간격 배율 적용", "間隔を伸縮"),
    "Scales the spacing of the selected keys around the first selected key (Alt+drag the last selected key on the timeline does the same).": (
        "첫 번째로 선택한 키를 기준으로 선택한 키 사이의 간격을 늘리거나 줄입니다. 타임라인에서 마지막으로 선택한 키를 Alt+드래그해도 됩니다.",
        "最初に選択したキーを基準に、選択したキーの間隔を伸縮します。タイムラインで最後に選択したキーを Alt+ドラッグしても同じです。"),
    "Add to selected keys": ("선택한 키에 더하기", "選択したキーに加算"),
    "Apply offset": ("오프셋 적용", "オフセットを適用"),
    "Shift or Ctrl+click adds a key. Drag on empty lane or graph space to box-select (Shift adds). Drag a selected key to move them all; Alt+drag the last one to stretch.": (
        "Shift 또는 Ctrl+클릭으로 키를 추가합니다. 레인이나 그래프의 빈 곳을 드래그하면 상자로 선택합니다(Shift: 추가). "
        "선택한 키를 드래그하면 함께 움직이고, 마지막 키를 Alt+드래그하면 간격을 늘이거나 줄입니다.",
        "Shift または Ctrl+クリックでキーを追加します。レーンやグラフの空いた所をドラッグすると範囲選択します（Shift: 追加）。"
        "選択したキーをドラッグするとまとめて動き、最後のキーを Alt+ドラッグすると間隔を伸縮します。"),
    "Move camera keys": ("선택한 카메라 키 이동", "選択したカメラキーを移動"),
    "Delete camera keys": ("선택한 카메라 키 삭제", "選択したカメラキーを削除"),
    "Scale camera key timing": ("카메라 키 간격 배율", "カメラキーの間隔を伸縮"),
    "Offset camera keys": ("카메라 키에 오프셋 더하기", "カメラキーにオフセットを加算"),
    "Paste camera keys": ("카메라 키 붙여넣기", "カメラキーを貼り付け"),
    "Camera keys copied: {count}.": ("카메라 키 {count}개를 복사했습니다.", "カメラキーを{count}個コピーしました。"),
    "Copy camera keys first.": ("먼저 카메라 키를 복사하세요.", "先にカメラキーをコピーしてください。"),
    "The copied keys do not fit in this shot.": ("복사한 키가 이 샷 안에 들어가지 않습니다.", "コピーしたキーはこのショットに収まりません。"),
    "Keys outside this shot were left out: {count}.": (
        "이 샷 범위를 벗어난 키 {count}개는 제외했습니다.", "このショットの範囲外のキー{count}個は除外しました。"),
    "Select at least two keys to scale their timing.": (
        "간격을 바꾸려면 키를 두 개 이상 선택하세요.", "間隔を変えるには、キーを2つ以上選択してください。"),
    "The timing stops at a neighbouring key or the end of the shot.": (
        "이웃한 키나 샷 끝에서 멈췄습니다.", "隣のキーかショットの端で止まりました。"),
    # Touch: "Select several" (no Shift or Ctrl on a phone).
    "Select several": ("여러 개 선택", "複数選択"),
    "While this is on, a tap adds or removes a key and a sideways drag on the camera lane selects the keys in a box. A long-press on a key also turns it on.": (
        "켜 두면 키를 탭할 때마다 선택에 더하거나 빼고, 카메라 레인을 가로로 드래그하면 상자 안의 키를 선택합니다. 키를 길게 눌러도 켜집니다.",
        "オンの間は、キーをタップするたびに選択に追加・解除し、カメラレーンを横にドラッグすると範囲内のキーを選択します。キーを長押ししてもオンになります。"),
    "Touch: turn on Select several (or long-press a key) and tap keys; drag sideways on the camera lane or on the graph to box-select. Drag a selected key to move them all.": (
        "터치: '여러 개 선택'을 켜거나 키를 길게 누른 뒤 키를 탭하세요. 카메라 레인이나 그래프를 가로로 드래그하면 상자로 선택합니다. "
        "선택한 키를 드래그하면 함께 움직입니다.",
        "タッチ: 「複数選択」をオンにするかキーを長押しして、キーをタップします。カメラレーンやグラフを横にドラッグすると範囲選択します。"
        "選択したキーをドラッグするとまとめて動きます。"),
    "Delete selected keys": ("선택한 키 삭제", "選択したキーを削除"),
    # Split-screen sub cameras ("Camera" is translated in the MV Studio table).
    "Main camera": ("메인 카메라", "メインカメラ"),
    "Sub camera {slot}": ("서브 카메라 {slot}", "サブカメラ {slot}"),
}
for _source, (_korean, _japanese) in _MV_EDITOR_C_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese


_COSTUME_CONVERSION_TRANSLATIONS = {
    "Costume platform conversion": ["코스튬 플랫폼 변환", "衣装のプラットフォーム変換"],
    "Convert a modified costume body for Android (APK) or iOS using the same costume from the output platform.": [
        "수정한 코스튬 본체를 출력 플랫폼의 동일한 의상 원본으로 변환합니다.",
        "変換先の同じ衣装を使って、改造した衣装本体を Android (APK) または iOS 用に変換します。"
    ],
    "Conversion direction": ["변환 방향", "変換の方向"],
    "Modified costume bundle": ["변환할 모드 의상 번들", "変換する改造済み衣装バンドル"],
    "Modified costume (.unity or ZIP)": ["변환할 모드 의상 (.unity 또는 ZIP)", "変換する改造済み衣装 (.unity または ZIP)"],
    "Select a Unity bundle or a Mod ZIP containing a costume for the source platform.": [
        "Unity 번들이나 변환 전 플랫폼의 의상이 포함된 모드 ZIP을 선택하세요.",
        "Unity バンドル、または変換元プラットフォームの衣装が入った Mod ZIP を選びます。"
    ],
    "Folder of modified costumes": ["변환할 모드 의상 폴더", "変換する改造済み衣装のフォルダ"],
    "Where to find the matching costume": ["출력 플랫폼의 원본 의상 선택", "変換先の元の衣装を選択"],
    "Find the same costume in game data": ["게임 데이터에서 같은 의상 찾기", "ゲームデータから同じ衣装を探す"],
    "Choose the original manually": ["원본 의상 직접 선택", "元の衣装を手動で選ぶ"],
    "Game packs folder (optional)": ["게임 packs 폴더 (선택)", "ゲームの packs フォルダ（任意）"],
    "Leave blank to use the configured packs folder. Only packs for the matching costume are read.": [
        "비워 두면 설정된 packs 폴더를 사용합니다. 같은 의상에 필요한 팩만 읽습니다.",
        "空欄の場合は設定済みの packs フォルダを使用し、該当する衣装のパックだけを読み込みます。"
    ],
    "Download any missing packs for the matching costume": ["이 의상에 필요한 누락 팩 다운로드", "該当する衣装に必要な不足パックをダウンロード"],
    "Original costume bundle for the output platform": ["출력 플랫폼의 같은 의상 원본 번들", "変換先プラットフォームの同じ衣装の元バンドル"],
    "Folder of extracted original costumes for the output platform": ["출력 플랫폼에서 추출한 원본 의상 폴더", "変換先プラットフォームから抽出した元の衣装のフォルダ"],
    "Leave blank to name the file for the output platform.": ["비워 두면 파일 이름에 출력 플랫폼이 붙습니다.", "空欄の場合はファイル名に変換先のプラットフォームが付きます。"],
    "Swing settings for existing bones and colliders": ["기존 본·콜라이더에 적용할 흔들림 설정", "既存のボーンとコライダーに適用する揺れ設定"],
    "Use swing settings from the output platform’s original costume": ["출력 플랫폼의 원본 의상 설정 사용", "変換先の元の衣装の揺れ設定を使う"],
    "Bring over the modified costume’s swing settings": ["변환할 모드 의상 설정 가져오기", "変換する改造済み衣装の揺れ設定を引き継ぐ"],
    "Use the iOS original costume’s swing settings": ["iOS 원본 의상의 흔들림 사용", "iOS の元の衣装の揺れ設定を使う"],
    "Use the Android original costume’s swing settings": ["Android 원본 의상의 흔들림 사용", "Android の元の衣装の揺れ設定を使う"],
    "Bring over the iOS mod costume’s swing settings": ["iOS 모드 의상의 흔들림 가져오기", "iOS の改造済み衣装の揺れ設定を引き継ぐ"],
    "Bring over the Android mod costume’s swing settings": ["Android 모드 의상의 흔들림 가져오기", "Android の改造済み衣装の揺れ設定を引き継ぐ"],
    "Both options keep new objects and physics added by a costume transplant.": [
        "어느 쪽을 선택해도 의상 이식으로 추가된 오브젝트와 물리 효과는 함께 옮겨집니다.",
        "どちらを選んでも、衣装の移植で追加されたオブジェクトや物理設定は引き継がれます。"
    ],
    "Convert costume": ["코스튬 변환", "衣装を変換"],
    "Check for a match again": ["같은 의상 다시 찾기", "同じ衣装を再検索"],
    "Choose the modified costume to find its original.": ["변환할 모드 의상을 선택하면 같은 의상의 원본을 찾습니다.", "改造済み衣装を選ぶと、同じ衣装の元データを探します。"],
    "Each costume is matched using the game catalog.": ["게임 목록에서 각 의상의 원본을 찾습니다.", "衣装ごとに元の衣装をゲームの一覧から探します。"],
    "Finding the original costume…": ["원본 의상 찾는 중…", "元の衣装を検索中…"],
    "Could not check the game data.": ["게임 데이터를 확인하지 못했습니다.", "ゲームデータを確認できませんでした。"],
    "Matching costume found in local game packs.": ["다운로드된 게임 팩에서 같은 의상 원본을 찾았습니다.", "ダウンロード済みのゲームパックに同じ衣装が見つかりました。"],
    "Matching costume found. Download its missing packs or choose the original manually.": [
        "같은 의상 원본을 찾았습니다. 필요한 팩을 다운로드하거나 원본을 직접 선택하세요.",
        "同じ衣装が見つかりました。不足パックをダウンロードするか、元の衣装を手動で選んでください。"
    ],
    "Choose the matching original costume manually.": ["같은 의상의 원본을 직접 선택하세요.", "同じ衣装の元データを手動で選んでください。"],
    "Choose the original costume and variant manually. The edited bundle could not be matched to the game catalog.": [
        "게임 목록에서 변환할 의상을 확인하지 못했습니다. 원본 의상과 종류를 직접 선택하세요.",
        "変換する衣装をゲームの一覧で確認できませんでした。元の衣装と種類を手動で選んでください。"
    ],
    "More than one original costume matches this bundle. Choose the costume and variant manually.": [
        "이 번들과 일치하는 원본이 여러 개 있습니다. 의상과 종류를 직접 선택하세요.",
        "このバンドルに一致する元の衣装が複数あります。衣装と種類を手動で選んでください。"
    ],
}
for _source, _translated in _COSTUME_CONVERSION_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _translated[0]
    _TABLES["ja"][_source] = _translated[1]


_MV_EDITOR_D_TRANSLATIONS = {
    "Follow camera": ("따라가기 카메라", "追従カメラ"),
    "Camera rigs (editor)": ("카메라 리그 (편집기)", "カメラリグ（エディター）"),
    "Follow cameras are editor rigs. They are baked into the camera shots they cover, which is what the game plays.": (
        "따라가기 카메라는 편집기 리그입니다. 리그가 덮는 카메라 샷에 구워지며, 게임은 그 샷을 재생합니다.",
        "追従カメラはエディターのリグです。重なるカメラショットに焼き込まれ、ゲームではそのショットが再生されます。"),
    "Add follow camera": ("따라가기 카메라 추가", "追従カメラを追加"),
    "Follow camera {index}": ("따라가기 카메라 {index}", "追従カメラ {index}"),
    "{label} copy": ("{label} 사본", "{label} のコピー"),
    "Makes a camera that follows a member, like a Cinemachine follow camera. It covers the shot at the playhead.": (
        "멤버를 따라가는 카메라를 만듭니다(Cinemachine의 팔로우 카메라와 비슷합니다). 재생 위치의 샷 구간에 추가됩니다.",
        "メンバーを追いかけるカメラを作ります（Cinemachine の追従カメラに近い動きです）。再生位置のショットの範囲に追加されます。"),
    "No members to follow. Add a performer first.": (
        "따라갈 멤버가 없습니다. 먼저 출연자를 추가하세요.", "追従するメンバーがいません。先に出演者を追加してください。"),
    "Rig": ("리그", "リグ"),
    "Rig name": ("리그 이름", "リグ名"),
    "Time range": ("구간", "区間"),
    "Start (s)": ("시작 (초)", "開始（秒）"),
    "End (s)": ("끝 (초)", "終了（秒）"),
    "Duplicate rig": ("리그 복제", "リグを複製"),
    "Delete rig": ("리그 삭제", "リグを削除"),
    "Target": ("대상", "対象"),
    "Body part": ("부위", "部位"),
    "Head (whole)": ("머리 전체", "頭全体"),
    "Camera view": ("카메라 시점", "カメラの視点"),
    "Front puts the camera on the audience side; Right is the member's right.": (
        "정면은 관객석 쪽, 오른쪽은 멤버의 오른쪽에 카메라를 둡니다.",
        "正面は客席側、右はメンバーの右側にカメラを置きます。"),
    "Front view": ("정면", "正面"),
    "Back view": ("후면", "背面"),
    "Left view": ("왼쪽", "左"),
    "Right view": ("오른쪽", "右"),
    "Custom view": ("사용자", "カスタム"),
    "Custom: the direction is this angle alone.": ("사용자: 이 각도만으로 방향을 정합니다.", "カスタム：この角度だけで向きを決めます。"),
    "Added to the preset direction.": ("프리셋 방향에 더해집니다.", "プリセットの向きに加算されます。"),
    "Reference": ("방향 기준", "向きの基準"),
    "Stage front": ("무대 정면", "ステージ正面"),
    "Member facing": ("멤버가 보는 방향", "メンバーの向き"),
    "Camera angle": ("카메라 각도", "カメラの角度"),
    "Fixed (follow position only)": ("위치만 따라가기 (각도 고정)", "位置だけ追従（角度固定）"),
    "Pan (follow angle only)": ("각도만 따라가기 (위치 고정)", "角度だけ追従（位置固定）"),
    "Look at member": ("위치·각도 모두 따라가기", "位置と角度の両方を追従"),
    "Fixed: the camera keeps its direction and only follows the member's position. Pan: the camera stays where the rig starts and only turns toward the member. Look at member: it moves and turns.": (
        "위치만: 카메라 방향은 그대로 두고 멤버의 위치만 따라 움직입니다. 각도만: 카메라는 리그 시작 위치에 그대로 있고 멤버 쪽으로만 돌아갑니다. 모두: 움직이면서 멤버 쪽으로 돌아갑니다.",
        "位置だけ：カメラの向きはそのままで、メンバーの位置だけを追って動きます。角度だけ：カメラはリグ開始位置にとどまり、メンバーの方へ向きだけを変えます。両方：動きながらメンバーの方を向きます。"),
    "Placement": ("배치", "配置"),
    "Framing": ("구도", "構図"),
    "Close-up": ("클로즈업", "クローズアップ"),
    "Medium shot": ("미디엄 샷", "ミディアムショット"),
    "Full shot": ("풀 샷", "フルショット"),
    "Camera height above the look-at point.": ("조준점보다 카메라가 높은 정도입니다.", "注視点から見たカメラの高さです。"),
    "+ moves the camera toward the member's right in the front view (the camera's left).": (
        "+ 값은 정면 시점에서 카메라를 멤버의 오른쪽(카메라 기준 왼쪽)으로 옮깁니다.",
        "＋の値は、正面の視点でカメラをメンバーの右側（カメラから見て左）へ動かします。"),
    "Moves the point the camera looks at, in the reference frame.": (
        "카메라가 바라보는 점을 방향 기준에 맞춰 옮깁니다.", "カメラが見る点を、向きの基準に沿って動かします。"),
    "Lens": ("렌즈", "レンズ"),
    "Dead zone": ("데드존", "デッドゾーン"),
    "Small moves inside the dead zone are ignored. Once the member leaves it, the camera follows until the member is back within radius × (1 − hysteresis).": (
        "데드존 안의 작은 움직임은 무시합니다. 멤버가 데드존을 벗어나면 반경 × (1 − 히스테리시스) 안으로 돌아올 때까지 따라갑니다.",
        "デッドゾーン内の小さな動きは無視します。メンバーが外に出ると、半径 ×（1 − ヒステリシス）の内側に戻るまで追いかけます。"),
    "Height lock": ("높이 고정", "高さ固定"),
    "Keeps the camera or the look-at point at one height, so jumps and crouches do not bob the camera.": (
        "카메라나 조준점의 높이를 고정해 점프나 웅크림에 카메라가 위아래로 흔들리지 않게 합니다.",
        "カメラまたは注視点の高さを固定し、ジャンプやしゃがみでカメラが上下しないようにします。"),
    "Lock": ("고정", "固定"),
    "Look-at point": ("조준점", "注視点"),
    "Locked height": ("고정할 높이", "固定する高さ"),
    "Height at the rig start": ("리그 시작 높이", "リグ開始時の高さ"),
    "Fixed height": ("지정 높이", "指定の高さ"),
    "Damping": ("댐핑", "ダンピング"),
    "How long the camera takes to catch up, in seconds (about 63 % of the way). 0 follows at once; larger values are smoother.": (
        "카메라가 따라잡는 데 걸리는 시간(초, 약 63% 지점)입니다. 0은 즉시 따라가고, 값이 클수록 부드럽습니다.",
        "カメラが追いつくまでの時間（秒、約63%に達するまで）です。0はすぐに追従し、大きいほど滑らかになります。"),
    "Blend": ("블렌드", "ブレンド"),
    "Fades from the shot's own camera and back. 0 is a cut.": (
        "원래 샷의 카메라에서 부드럽게 넘어왔다가 돌아갑니다. 0은 바로 전환합니다.",
        "元のショットのカメラから滑らかに切り替わり、また戻ります。0はカットです。"),
    "Yaw offset (°)": ("방향 회전 (°)", "向きの回転 (°)"),
    "Turn damping (s)": ("회전 댐핑 (초)", "回転ダンピング（秒）"),
    "Distance (m)": ("거리 (m)", "距離 (m)"),
    "Height (m)": ("높이 (m)", "高さ (m)"),
    "Side offset (m)": ("좌우 이동 (m)", "左右のずらし (m)"),
    "Look-at height (m)": ("조준 높이 (m)", "注視点の高さ (m)"),
    "Look-at side (m)": ("조준 좌우 (m)", "注視点の左右 (m)"),
    "Look-at forward (m)": ("조준 앞뒤 (m)", "注視点の前後 (m)"),
    "FOV (°)": ("화각 (°)", "画角 (°)"),
    "Roll (°)": ("롤 (°)", "ロール (°)"),
    "Radius (m)": ("반경 (m)", "半径 (m)"),
    "Height band (m)": ("높이 범위 (m)", "高さの範囲 (m)"),
    "Hysteresis": ("히스테리시스", "ヒステリシス"),
    "Fixed height (m)": ("지정 높이 (m)", "指定の高さ (m)"),
    "Look-at XZ (s)": ("조준 수평 (초)", "注視点 水平（秒）"),
    "Look-at Y (s)": ("조준 수직 (초)", "注視点 垂直（秒）"),
    "Camera XZ (s)": ("카메라 수평 (초)", "カメラ 水平（秒）"),
    "Camera Y (s)": ("카메라 수직 (초)", "カメラ 垂直（秒）"),
    "Blend in (s)": ("블렌드 인 (초)", "ブレンドイン（秒）"),
    "Blend out (s)": ("블렌드 아웃 (초)", "ブレンドアウト（秒）"),
    "The follow camera is baked for the current members and outfits. Other MV decks can frame differently. For registered MVs, Height lock: Camera is recommended.": (
        "따라가기 카메라는 현재 멤버와 의상을 기준으로 구워집니다. 다른 MV 덱에서는 구도가 달라질 수 있습니다. 게임에 등록할 MV에는 '높이 고정: 카메라'를 권장합니다.",
        "追従カメラは現在のメンバーと衣装を基準に焼き込まれます。別のMVデッキでは構図が変わることがあります。登録するMVには「高さ固定：カメラ」をおすすめします。"),
    "Baking camera… {percent}%": ("카메라 굽는 중… {percent}%", "カメラを焼き込み中… {percent}%"),
    "Bake again": ("다시 굽기", "もう一度焼き込む"),
    "Baking was cancelled. The shots keep their previous camera.": (
        "굽기를 취소했습니다. 샷은 이전 카메라를 유지합니다.", "焼き込みを取り消しました。ショットは前のカメラのままです。"),
    "Waiting for the 3D preview…": ("3D 미리보기를 기다리는 중…", "3Dプレビューを待っています…"),
    "The 3D preview is not available, so the follow camera cannot be baked.": (
        "3D 미리보기를 사용할 수 없어 따라가기 카메라를 구울 수 없습니다.", "3Dプレビューが使えないため、追従カメラを焼き込めません。"),
    "This member is not loaded in the 3D preview.": (
        "이 멤버가 3D 미리보기에 불러와지지 않았습니다.", "このメンバーは3Dプレビューに読み込まれていません。"),
    "This member has no target for the chosen body part.": (
        "이 멤버에는 선택한 부위의 기준점이 없습니다.", "このメンバーには選んだ部位の基準点がありません。"),
    "This member has no facing; the stage front is used.": (
        "이 멤버는 방향 정보가 없어 무대 정면을 기준으로 합니다.", "このメンバーには向きの情報がないため、ステージ正面を基準にします。"),
    "No camera shot is under this rig, so it moves nothing.": (
        "이 리그 아래에 카메라 샷이 없어 아무것도 움직이지 않습니다.", "このリグの下にカメラショットがないため、何も動きません。"),
    "{label} · {start}–{end} · Member {slot}": ("{label} · {start}–{end} · 멤버 {slot}", "{label} · {start}–{end} · メンバー{slot}"),
    "Baking the follow camera was cancelled. Try again to bake it, or delete the rig.": (
        "따라가기 카메라 굽기가 취소되었습니다. 다시 시도해 굽거나 리그를 삭제하세요.",
        "追従カメラの焼き込みが取り消されました。もう一度焼き込むか、リグを削除してください。"),
    "A follow camera has no member to follow. Choose a loaded member or delete the rig before exporting.": (
        "따라갈 멤버가 없는 따라가기 카메라가 있습니다. 내보내기 전에 불러온 멤버를 고르거나 리그를 삭제하세요.",
        "追従するメンバーがいない追従カメラがあります。書き出す前に、読み込まれたメンバーを選ぶかリグを削除してください。"),
    "Edit follow camera": ("따라가기 카메라 편집", "追従カメラを編集"),
    "Move follow camera": ("따라가기 카메라 이동", "追従カメラを移動"),
    "Resize follow camera": ("따라가기 카메라 길이 변경", "追従カメラの長さを変更"),
    "Duplicate follow camera": ("따라가기 카메라 복제", "追従カメラを複製"),
    "Delete follow camera": ("따라가기 카메라 삭제", "追従カメラを削除"),
}
for _source, (_korean, _japanese) in _MV_EDITOR_D_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese


_MV_STUDIO_TRANSLATIONS = {
    "Panel settings": ("패널 설정", "パネル設定"),
    "Load MV from game": ("게임에서 MV 불러오기", "ゲームからMVを読み込む"),
    "Open mod or project": ("모드 또는 프로젝트 열기", "Modまたはプロジェクトを開く"),
    "Save MV project": ("MV 프로젝트 저장", "MVプロジェクトを保存"),
    "Export native timeline": ("게임용 타임라인 내보내기", "ゲーム用タイムラインを書き出す"),
    "Exporting native timeline…": ("게임용 타임라인 내보내는 중…", "ゲーム用タイムラインを書き出し中…"),
    "Native timeline exported.": ("게임용 타임라인을 내보냈습니다.", "ゲーム用タイムラインを書き出しました。"),
    "Open an MV to preview its stage and timeline.": ("MV를 열면 무대와 타임라인을 볼 수 있습니다.", "MVを開くとステージとタイムラインを確認できます。"),
    "The 3D preview could not prepare its materials before playback. They are prepared when first shown.": (
        "3D 미리보기가 재생 전에 재질을 미리 준비하지 못했습니다. 처음 표시될 때 준비합니다.",
        "3Dプレビューで再生前にマテリアルを準備できませんでした。最初に表示されるときに準備します。"),
    "This MV has no visual assets available for preview.": ("이 MV에서 미리 볼 수 있는 모델을 찾지 못했습니다.", "このMVにはプレビューできるモデルがありません。"),
    "Preview camera": ("미리보기 카메라", "プレビューカメラ"),
    "Game camera": ("게임 카메라", "ゲームカメラ"),
    "Start and end fade": ("시작·종료 페이드", "開始・終了フェード"),
    "Free camera": ("자유 카메라", "自由カメラ"),
    "Frame scene": ("무대 전체 보기", "ステージ全体を表示"),
    "MV assets": ("MV 에셋", "MVアセット"),
    "Tracks": ("트랙", "トラック"),
    "Selected event": ("선택한 이벤트", "選択したイベント"),
    "MV quality settings": ("MV 그래픽 설정", "MVグラフィック設定"),
    "Choose ACB": ("ACB 선택", "ACBを選択"),
    "Choose AWB": ("AWB 선택", "AWBを選択"),
    "Restart the game server to load the updated catalog.": ("목록 변경을 게임에 적용하려면 게임 서버를 재시작하세요.", "更新した一覧をゲームに反映するには、ゲームサーバーを再起動してください。"),
    "Load chart templates": ("채보 템플릿 불러오기", "譜面テンプレートを読み込む"),
    "Loading chart templates…": ("채보 템플릿 불러오는 중…", "譜面テンプレートを読み込み中…"),
    "No compatible chart templates.": ("호환되는 채보 템플릿을 찾지 못했습니다.", "対応する譜面テンプレートがありません。"),
    "Chart template": ("채보 템플릿", "譜面テンプレート"),
    "Choose chart file": ("채보 파일 선택", "譜面ファイルを選択"),
    "Attach chart": ("채보 연결", "譜面を追加"),
    "Attaching chart…": ("채보 연결 중…", "譜面を追加中…"),
    "Chart attached.": ("채보를 연결했습니다.", "譜面を追加しました。"),
    "Import notes": ("불러오기 결과", "読み込み結果"),
    "MV timeline": ("MV 타임라인", "MVタイムライン"),
    "Timeline height": ("타임라인 높이", "タイムラインの高さ"),
    "Drag upward or press the Up arrow to make the timeline taller. Home restores the default. End sets the maximum.": (
        "위로 드래그하거나 위쪽 화살표 키를 누르면 타임라인이 커집니다. Home 키는 기본 높이로, End 키는 최대 높이로 바꿉니다.",
        "上へドラッグするか上矢印キーを押すと、タイムラインが広がります。Homeキーで標準の高さに戻し、Endキーで最大にします。",
    ),
    "Go to start": ("처음으로", "先頭へ"),
    "Playhead": ("재생 위치", "再生位置"),
    "Timeline scale": ("타임라인 배율", "タイムライン倍率"),
    "Fit to width": ("폭에 맞추기", "幅に合わせる"),
    "Search MVs": ("MV 검색", "MVを検索"),
    "Song": ("곡", "楽曲"),
    "MV variant": ("MV 버전", "MVの種類"),
    "MV deck": ("MV 덱", "MVデッキ"),
    "Customize": ("커스터마이즈", "カスタマイズ"),
    "Original": ("오리지널", "オリジナル"),
    "Player": ("플레이어", "プレイヤー"),
    "New player": ("새 플레이어", "新しいプレイヤー"),
    "Game costume": ("게임 의상", "ゲームの衣装"),
    # Not bare "View": the global table would also rename the texture tools' View menu.
    "View status": ("뷰 상태", "ビュー状態"),
    "Load MV": ("MV 불러오기", "MVを読み込む"),
    "MV only": ("MV 전용", "MV専用"),
    "MV stage {n}": ("MV {n}번", "MV {n}番"),
    "Live 3D only": ("라이브 3D 전용", "ライブ3D専用"),
    "Not in the MV list": ("MV 목록에 없음", "MV一覧にない"),
    "Loading MVs…": ("MV 목록 불러오는 중…", "MV一覧を読み込み中…"),
    "No matching MVs.": ("일치하는 MV를 찾지 못했습니다.", "該当するMVが見つかりません。"),
    "Preparing MV from game…": ("게임에서 MV 준비 중…", "ゲームデータからMVを準備中…"),
    "Opening MV…": ("MV를 여는 중…", "MVを開いています…"),
    "Importing MV asset…": ("MV 에셋을 불러오는 중…", "MVアセットを読み込み中…"),
    "Saving MV project…": ("MV 프로젝트를 저장하는 중…", "MVプロジェクトを保存中…"),
    "MV project saved.": ("MV 프로젝트를 저장했습니다.", "MVプロジェクトを保存しました。"),
    "Download MV project": ("MV 프로젝트 다운로드", "MVプロジェクトをダウンロード"),
    "No MV is open.": ("열린 MV가 없습니다.", "MVが開かれていません。"),
    "Import MV asset": ("MV 에셋 불러오기", "MVアセットを読み込む"),
    "Asset type": ("에셋 종류", "アセットの種類"),
    "Performer outfit": ("출연자 의상", "出演者の衣装"),
    "Performers": ("출연자", "出演者"),
    "Performer": ("출연자", "出演者"),
    "No performers are loaded.": ("불러온 출연자가 없습니다.", "読み込まれた出演者がいません。"),
    "Replace outfit": ("의상 교체", "衣装を交換"),
    "This MV already has twelve performers. Choose an existing performer to replace their outfit.": [
        "이 MV에는 이미 출연자가 12명 있습니다. 기존 출연자를 선택해 의상을 교체하세요.",
        "このMVには出演者がすでに12人います。既存の出演者を選んで衣装を交換してください。"
    ],
    "Props": ("소품", "小道具"),
    "Effects": ("이펙트", "エフェクト"),
    "Soundtrack": ("음원", "音源"),
    "Soundtrack offset (s)": ("음원 오프셋 (초)", "音源オフセット（秒）"),
    "Import soundtrack": ("음원 불러오기", "音源を読み込む"),
    "Other asset": ("기타 에셋", "その他のアセット"),
    "Track type": ("트랙 종류", "トラックの種類"),
    "All tracks": ("모든 트랙", "すべてのトラック"),
    "No timeline events.": ("타임라인 이벤트가 없습니다.", "タイムラインにイベントがありません。"),
    "Select an event in the timeline.": ("타임라인에서 이벤트를 선택하세요.", "タイムラインでイベントを選択してください。"),
    "Start time (s)": ("시작 시간 (초)", "開始時間（秒）"),
    "Field of view (FOV)": ("시야각 (FOV)", "視野角（FOV）"),
    "Parameter name": ("매개변수 이름", "パラメーター名"),
    "Clip offset (s)": ("클립 오프셋 (초)", "クリップオフセット（秒）"),
    "Before clip": ("클립 이전", "クリップの前"),
    "After clip": ("클립 이후", "クリップの後"),
    "Hold": ("정지", "保持"),
    "Ping-pong": ("왕복", "往復"),
    "Keyframes": ("키프레임", "キーフレーム"),
    "Light intensity": ("조명 밝기", "ライトの強さ"),
    "Duration (s)": ("길이 (초)", "長さ（秒）"),
    "Entry number": ("항목 번호", "項目番号"),
    "No MV quality settings were imported.": ("불러온 MV 그래픽 설정이 없습니다.", "読み込まれたMVグラフィック設定はありません。"),
    "Quality preset": ("그래픽 프리셋", "グラフィックプリセット"),
    "Refresh-rate mode": ("주사율 모드", "リフレッシュレートモード"),
    "Anti-aliasing": ("안티에일리어싱", "アンチエイリアス"),
    "Soundtrack playback is unavailable. The timeline is still playing.": ("음원을 재생할 수 없어 타임라인만 재생합니다.", "音源を再生できないためタイムラインのみ再生します。"),
    "The imported MV project is invalid.": ("불러온 MV 프로젝트 형식이 올바르지 않습니다.", "読み込んだMVプロジェクトの形式が正しくありません。"),
    "The MV could not be loaded.": ("MV를 불러오지 못했습니다.", "MVを読み込めませんでした。"),
    "The MV asset could not be imported.": ("MV 에셋을 불러오지 못했습니다.", "MVアセットを読み込めませんでした。"),
    "The MV project could not be saved.": ("MV 프로젝트를 저장하지 못했습니다.", "MVプロジェクトを保存できませんでした。"),
    "Camera": ("카메라", "カメラ"),
    "Dance": ("댄스", "ダンス"),
    "Gaze": ("시선", "視線"),
    "Cheek": ("볼", "頬"),
    "Sound": ("소리", "サウンド"),
    "Lighting": ("조명", "照明"),
    "Display": ("표시", "表示"),
    "Bloom": ("블룸", "ブルーム"),
    "Depth of field": ("피사계 심도", "被写界深度"),
    "Stage": ("무대", "ステージ"),
    "Crowd": ("관객", "観客"),
    "Split screen": ("화면 분할", "画面分割"),
    # Game import progress (mv-studio-import-progress.js; the server's plan sends the same step labels).
    "Reading game data…": ("게임 데이터를 읽는 중…", "ゲームデータを読み込み中…"),
    "Reading the live timeline…": ("라이브 타임라인을 분석하는 중…", "ライブタイムラインを解析中…"),
    "Converting the stage…": ("무대를 변환하는 중…", "ステージを変換中…"),
    "Converting stage effects…": ("무대 이펙트를 변환하는 중…", "ステージエフェクトを変換中…"),
    "Converting stage props…": ("무대 소품을 변환하는 중…", "ステージの小道具を変換中…"),
    "Converting member {index}/{count}: {name}": ("멤버 변환 중 {index}/{count}: {name}", "メンバーを変換中 {index}/{count}: {name}"),
    "Decoding the soundtrack…": ("음원을 디코딩하는 중…", "楽曲をデコード中…"),
    "Finishing the MV project…": ("MV 프로젝트를 마무리하는 중…", "MVプロジェクトを仕上げ中…"),
    "Opening the timeline bundle…": ("타임라인 번들을 여는 중…", "タイムラインバンドルを開いています…"),
    "Reading timeline tracks…": ("타임라인 트랙을 읽는 중…", "タイムライントラックを読み込み中…"),
    "Stage effects {done}/{total}": ("무대 연출 {done}/{total}", "ステージ演出 {done}/{total}"),
    "Reading choreography…": ("안무 데이터를 읽는 중…", "振り付けデータを読み込み中…"),
    "Textures {done}": ("텍스처 {done}개", "テクスチャ {done}枚"),
    "Building dance motion… {done}%": ("댄스 모션을 만드는 중… {done}%", "ダンスモーションを生成中… {done}%"),
    "Loading 3D models {done}/{total}…": ("3D 모델을 불러오는 중 {done}/{total}…", "3Dモデルを読み込み中 {done}/{total}…"),
    "Loading 3D models…": ("3D 모델을 불러오는 중…", "3Dモデルを読み込み中…"),
    "Ready to play": ("재생 준비 완료", "再生の準備ができました"),
    "Preparing effects…": ("이펙트를 준비하는 중…", "エフェクトを準備中…"),
    "Reused from cache": ("캐시에서 재사용", "キャッシュから再利用"),
    "Stage is ready. Members are still loading.": ("무대가 준비되었습니다. 멤버를 불러오는 중입니다.", "ステージの準備ができました。メンバーを読み込み中です。"),
    "Members done {done}/{count}": ("멤버 {done}/{count} 완료", "メンバー {done}/{count} 完了"),
    "Game data {read}/{total} MB": ("게임 데이터 {read}/{total} MB", "ゲームデータ {read}/{total} MB"),
    "Cancel import": ("불러오기 취소", "読み込みをキャンセル"),
    "Cancelling…": ("취소하는 중…", "キャンセル中…"),
    "MV import cancelled.": ("MV 불러오기를 취소했습니다.", "MVの読み込みをキャンセルしました。"),
    # Game import errors (mv_studio.load_game and mv_studio_game) a person can meet.
    "An MV is already being prepared. Try again when it finishes.": (
        "다른 MV를 준비하는 중입니다. 끝난 뒤 다시 시도하세요.", "別のMVを準備中です。終わってからもう一度お試しください。"),
    "The original MV timeline pack is missing. Download its missing assets or choose a local mod file.": (
        "원본 MV 타임라인 팩이 없습니다. 누락된 에셋을 다운로드하거나 로컬 모드 파일을 선택하세요.",
        "元のMVタイムラインパックがありません。不足しているアセットをダウンロードするか、ローカルのMODファイルを選んでください。"),
    "This file does not contain an original live timeline.": (
        "이 파일에는 원본 라이브 타임라인이 없습니다.", "このファイルには元のライブタイムラインが含まれていません。"),
    "The original MV timeline exceeds the supported size.": (
        "원본 MV 타임라인이 지원하는 크기를 넘습니다.", "元のMVタイムラインが対応サイズを超えています。"),
    "The stage preview or soundtrack exceeds the supported size.": (
        "무대 미리보기나 음원이 지원하는 크기를 넘습니다.", "ステージプレビューまたは楽曲が対応サイズを超えています。"),
    "The 3D preview expired. Reopen the asset.": (
        "3D 미리보기가 만료되었습니다. 에셋을 다시 여세요.", "3Dプレビューの有効期限が切れました。アセットを開き直してください。"),
    "Reading the selected MV assets took too long. Try again.": (
        "선택한 MV 에셋을 읽는 데 시간이 너무 오래 걸렸습니다. 다시 시도하세요.",
        "選択したMVアセットの読み込みに時間がかかりすぎました。もう一度お試しください。"),
    "The selected game MV and stage are no longer available. Refresh the list.": (
        "선택한 게임 MV와 무대를 더 이상 사용할 수 없습니다. 목록을 새로 고치세요.",
        "選択したゲームのMVとステージは利用できなくなりました。リストを更新してください。"),
    "The selected game pack changed during import. Try again.": (
        "불러오는 동안 선택한 게임 팩이 바뀌었습니다. 다시 시도하세요.", "読み込み中に選択したゲームパックが変更されました。もう一度お試しください。"),
    "The selected game pack section is incomplete.": (
        "선택한 게임 팩 섹션이 불완전합니다.", "選択したゲームパックのセクションが不完全です。"),
    "The selected MV stage has no game stage model reference.": (
        "선택한 MV 무대에 게임 무대 모델 참조가 없습니다.", "選択したMVステージにはゲームのステージモデル参照がありません。"),
    "The selected sound pack has an invalid CRI header.": (
        "선택한 사운드 팩의 CRI 헤더가 올바르지 않습니다.", "選択したサウンドパックのCRIヘッダーが無効です。"),
    "A requested costume has no member at its position in this MV.": (
        "요청한 의상의 위치에 이 MV의 멤버가 없습니다.", "指定した衣装の位置に、このMVのメンバーがいません。"),
    "Choose a valid game MV and stage.": ("올바른 게임 MV와 무대를 선택하세요.", "有効なゲームのMVとステージを選んでください。"),
    "Choose valid costumes for the MV members.": ("MV 멤버에게 올바른 의상을 선택하세요.", "MVメンバーに有効な衣装を選んでください。"),
    "Choose a supported game region and asset platform.": (
        "지원하는 게임 지역과 에셋 플랫폼을 선택하세요.", "対応しているゲーム地域とアセットプラットフォームを選んでください。"),
    "This MV has too many linked game assets.": ("이 MV에 연결된 게임 에셋이 너무 많습니다.", "このMVにリンクされたゲームアセットが多すぎます。"),
    "The game contains too many 3D MV catalog rows.": (
        "게임의 3D MV 카탈로그 항목이 너무 많습니다.", "ゲームの3D MVカタログ行が多すぎます。"),
}
for _source, (_korean, _japanese) in _MV_STUDIO_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# MV Studio editor lane A: timeline tabs and filters, undo/redo, clip editing.
_MV_EDITOR_A_TRANSLATIONS = {
    "Edit": ("편집", "編集"),
    "All": ("전체", "すべて"),
    "Expression": ("표정", "表情"),
    "Screen effects": ("화면 효과", "画面効果"),
    "Other": ("기타", "その他"),
    "Timeline categories": ("타임라인 분류", "タイムラインの分類"),
    "Tracks: {tracks} · Clips: {clips}": ("트랙 {tracks}개 · 클립 {clips}개", "トラック{tracks}件 · クリップ{clips}件"),
    "Members": ("멤버", "メンバー"),
    "All members": ("전체 멤버", "全メンバー"),
    "Member": ("멤버", "メンバー"),
    "Search tracks": ("트랙 이름 검색", "トラック名で検索"),
    "Show editable tracks only": ("편집 가능한 트랙만 보기", "編集できるトラックのみ表示"),
    "The Edit tab already lists edited and editable tracks.": (
        "편집 탭에는 이미 편집한 트랙과 편집 가능한 트랙만 나옵니다.",
        "編集タブには編集したトラックと編集できるトラックだけが表示されます。",
    ),
    "Native group": ("원본 그룹", "元のグループ"),
    "All groups": ("모든 그룹", "すべてのグループ"),
    "{tracks} tracks · {clips} clips · {edited} edited": (
        "트랙 {tracks}개 · 클립 {clips}개 · 편집 {edited}개", "トラック{tracks}件 · クリップ{clips}件 · 編集{edited}件"),
    "Editable": ("편집 가능", "編集可能"),
    "No edits yet. Editable tracks are listed below.": (
        "아직 편집한 항목이 없습니다. 편집할 수 있는 트랙은 아래에 있습니다.",
        "まだ編集していません。編集できるトラックは下にあります。",
    ),
    "Edited": ("편집됨", "編集済み"),
    "Undo": ("실행 취소", "元に戻す"),
    "Redo": ("다시 실행", "やり直す"),
    "Undo: {label}": ("실행 취소: {label}", "元に戻す: {label}"),
    "Redo: {label}": ("다시 실행: {label}", "やり直す: {label}"),
    "Nothing to undo": ("실행 취소할 작업이 없습니다", "元に戻す操作はありません"),
    "Nothing to redo": ("다시 실행할 작업이 없습니다", "やり直す操作はありません"),
    "Move clip": ("클립 이동", "クリップを移動"),
    "Resize clip": ("클립 길이 변경", "クリップの長さを変更"),
    "Rename clip": ("클립 이름 변경", "クリップ名を変更"),
    "Edit value": ("값 편집", "値を編集"),
    "Revert clip": ("클립 되돌리기", "クリップを元に戻す"),
    "Duplicate clip": ("클립 복제", "クリップを複製"),
    "Delete clip": ("클립 삭제", "クリップを削除"),
    "Move performer": ("출연자 위치 변경", "出演者の位置を変更"),
    "Change soundtrack offset": ("음원 오프셋 변경", "音源オフセットを変更"),
    "Change quality preset": ("그래픽 프리셋 변경", "グラフィックプリセットを変更"),
    "Change quality setting": ("그래픽 설정 변경", "グラフィック設定を変更"),
    "Clip name": ("클립 이름", "クリップ名"),
    "Recomputed by the game": ("게임이 다시 계산하는 값입니다", "ゲームが再計算する値です"),
    "Some timeline edits could not be carried over.": (
        "일부 타임라인 편집 내용을 옮기지 못했습니다.", "一部のタイムライン編集を引き継げませんでした。"),
    "Wait for the current MV task to finish.": ("진행 중인 MV 작업이 끝날 때까지 기다려 주세요.", "実行中のMV処理が終わるまでお待ちください。"),
    "This clip's timing cannot be edited.": ("이 클립의 시간은 편집할 수 없습니다.", "このクリップの時間は編集できません。"),
    "Drag a clip to move it and its right edge to change its length. Alt+Left or Alt+Right moves the clip by one frame, with Shift by ten frames.": (
        "클립을 드래그하면 이동하고, 오른쪽 끝을 드래그하면 길이가 바뀝니다. Alt+왼쪽/오른쪽 화살표로 1프레임씩, Shift를 함께 누르면 10프레임씩 옮깁니다.",
        "クリップをドラッグすると移動し、右端をドラッグすると長さが変わります。Alt+左右矢印キーで1フレームずつ、Shiftを併用すると10フレームずつ移動します。",
    ),
}
for _source, (_korean, _japanese) in _MV_EDITOR_A_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# MV Studio timeline host (mv-studio.js): derived blends, timing fields per clip type,
# track mute and quality badges.
_MV_EDITOR_E2_TRANSLATIONS = {
    "Set by the overlap with the next or previous clip": (
        "앞뒤 클립과 겹치는 길이로 정해집니다", "前後のクリップと重なる長さで決まります"),
    "The game does not use these timing fields of this clip type: {fields}.": (
        "이 클립 종류에서 게임이 쓰지 않는 시간 항목: {fields}.", "このクリップの種類でゲームが使わない時間項目: {fields}。"),
    "Before and after the clip": ("클립 앞뒤", "クリップの前後"),
    "Clip offset": ("클립 오프셋", "クリップオフセット"),
    "Playback speed": ("재생 속도", "再生速度"),
    "Ease and blend": ("이즈와 블렌드", "イーズとブレンド"),
    "Camera shots keep their offset and speed and offer None or Hold, the modes the preview shows.": (
        "카메라 샷은 오프셋과 속도를 바꿀 수 없고, 미리보기에 나오는 없음과 정지만 고를 수 있습니다.",
        "カメラショットはオフセットと速度を変えられず、プレビューに出る「なし」と「保持」だけを選べます。"),
    "Camera shots keep their offset and speed: the preview plays the samples read from the shot.": (
        "카메라 샷은 오프셋과 속도를 바꿀 수 없습니다. 미리보기는 샷에서 읽은 샘플을 그대로 재생합니다.",
        "カメラショットはオフセットと速度を変えられません。プレビューはショットから読んだサンプルをそのまま再生します。"),
    "Restore original value": ("원래 값으로 되돌리기", "元の値に戻す"),
    # The extrapolation mode after None, Hold (and before Ping-pong, Continue), which have theirs.
    "Loop": ("반복", "ループ"),
    "This shot overlaps another: the game crossfades them, the preview cuts to the later shot.": (
        "이 샷은 다른 샷과 겹칩니다. 게임은 두 샷을 겹쳐 전환하지만, 미리보기는 뒤의 샷으로 바로 바뀝니다.",
        "このショットは別のショットと重なっています。ゲームでは重ねて切り替わりますが、プレビューは後のショットにすぐ切り替わります。"),
    "{tracks} tracks · {clips} clips · {edited} edited · {follow} with recomputed blends or times": (
        "트랙 {tracks}개 · 클립 {clips}개 · 편집 {edited}개 · 블렌드나 시간만 다시 계산된 클립 {follow}개",
        "トラック{tracks}件 · クリップ{clips}件 · 編集{edited}件 · ブレンドや時間だけ再計算されたクリップ{follow}件"),
    "Mute track": ("트랙 음소거", "トラックをミュート"),
    "Unmute track": ("트랙 음소거 해제", "トラックのミュートを解除"),
    "Muted": ("음소거됨", "ミュート中"),
    "Muted group": ("음소거된 그룹", "ミュート中のグループ"),
    "This track is muted. The preview skips it.": (
        "이 트랙은 음소거되어 미리보기에서 재생되지 않습니다.", "このトラックはミュート中で、プレビューでは再生されません。"),
    "A group's mute does not reach the game: the game plays each track in it by its own mute.": (
        "그룹 음소거는 게임에 반영되지 않습니다. 게임은 그룹 안의 각 트랙을 그 트랙의 음소거 설정대로 재생합니다.",
        "グループのミュートはゲームに反映されません。ゲームはグループ内の各トラックを、そのトラック自身のミュート設定で再生します。"),
    "The game sets this track's mute from the {option} quality setting when the MV starts.": (
        "이 트랙의 음소거는 MV가 시작될 때 게임이 '{option}' 그래픽 설정에 따라 정합니다.",
        "このトラックのミュートは、MVの開始時にゲームが「{option}」のグラフィック設定に合わせて決めます。"),
    "The game sets this track's mute from the MV quality settings when the MV starts.": (
        "이 트랙의 음소거는 MV가 시작될 때 게임이 MV 그래픽 설정에 따라 정합니다.",
        "このトラックのミュートは、MVの開始時にゲームがMVのグラフィック設定に合わせて決めます。"),
    "The game sets the mute of eye and mouth tracks itself when the MV starts.": (
        "눈과 입 트랙의 음소거는 MV가 시작될 때 게임이 직접 정합니다.",
        "目と口のトラックのミュートは、MVの開始時にゲームが自分で決めます。"),
    # English names of the stage quality flags (core/mv_studio_quality._FIELDS) for a project without options.
    "Stage ambient lighting": ("무대 환경광", "ステージ環境光"),
    "Stage animation": ("무대 애니메이션", "ステージアニメーション"),
    "Stage coloring": ("무대 색상 연출", "ステージの色演出"),
    "Stage controls": ("무대 제어", "ステージ制御"),
    "Stage overlay effects": ("무대 오버레이 효과", "ステージのオーバーレイ効果"),
    "Stage flash lighting": ("무대 점멸 조명", "ステージの点滅照明"),
    "Stage displays": ("무대 화면", "ステージのスクリーン"),
    "Post-processing effects": ("후처리 효과", "ポストエフェクト"),
    "Stage emissive surfaces": ("무대 발광 표면", "ステージの発光面"),
    # "Audience" (관객/観客) comes from the editor lane B table.
    "Plays only while {option} is on in the MV quality settings.": (
        "MV 그래픽 설정에서 '{option}'이(가) 켜져 있을 때만 재생됩니다.", "MVのグラフィック設定で「{option}」がオンのときだけ再生されます。"),
    "Its tracks play only while {option} is on in the MV quality settings.": (
        "이 그룹의 트랙은 MV 그래픽 설정에서 '{option}'이(가) 켜져 있을 때만 재생됩니다.",
        "このグループのトラックは、MVのグラフィック設定で「{option}」がオンのときだけ再生されます。"),
    "{option} is off in the MV quality settings, so the game mutes this track.": (
        "MV 그래픽 설정에서 '{option}'이(가) 꺼져 있어 게임은 이 트랙을 재생하지 않습니다.",
        "MVのグラフィック設定で「{option}」がオフなので、ゲームはこのトラックを再生しません。"),
    "{option} is off in the MV quality settings, so the game mutes its tracks.": (
        "MV 그래픽 설정에서 '{option}'이(가) 꺼져 있어 게임은 이 그룹의 트랙을 재생하지 않습니다.",
        "MVのグラフィック設定で「{option}」がオフなので、ゲームはこのグループのトラックを再生しません。"),
}
for _source, (_korean, _japanese) in _MV_EDITOR_E2_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# MV Studio free camera views (mv-studio-free-camera.js). Front, Back, Left side, Right side
# and FOV are the 3D model tab's and the camera editor's strings.
_MV_FREE_CAMERA_TRANSLATIONS = {
    "Free camera views": ("자유 카메라 시점", "自由カメラの視点"),
    "Views": ("시점", "視点"),
    "Show or hide the free camera views. A short preview keeps them folded so the view stays visible.": (
        "자유 카메라 시점 조절을 펼치거나 접습니다. 미리보기 높이가 낮으면 화면이 가려지지 않도록 접어 둡니다.",
        "自由カメラの視点操作を開閉します。プレビューが低いときは画面が隠れないよう畳んでおきます。"),
    # "Target" (대상/対象) comes from the follow camera table (_MV_EDITOR_D_TRANSLATIONS).
    "Stage centre": ("무대 중앙", "ステージ中央"),
    "The free camera looks at this point and turns around it.": (
        "자유 카메라가 이 지점을 바라보며 그 주위를 돕니다.", "自由カメラはこの点を見ながら、その周りを回ります。"),
    "View direction": ("보는 방향", "見る方向"),
    "Look from the audience side (the side the members face).": (
        "관객석 쪽(멤버가 바라보는 쪽)에서 봅니다.", "客席側（メンバーが向いている側）から見ます。"),
    "Look from behind the stage.": ("무대 뒤쪽에서 봅니다.", "ステージの後ろ側から見ます。"),
    "Look from the members' left.": ("멤버의 왼쪽에서 봅니다.", "メンバーの左側から見ます。"),
    "Look from the members' right.": ("멤버의 오른쪽에서 봅니다.", "メンバーの右側から見ます。"),
    "Distance": ("거리", "距離"),
    "Distance from the target (m). The mouse wheel also moves the camera forward and back.": (
        "대상과의 거리(m)입니다. 마우스 휠로도 카메라를 앞뒤로 움직일 수 있습니다.",
        "対象からの距離（m）です。マウスホイールでもカメラを前後に動かせます。"),
    "Vertical field of view (°). Shift+mouse wheel also changes it.": (
        "세로 화각(°)입니다. Shift+마우스 휠로도 바꿀 수 있습니다.", "縦の画角（°）です。Shift+マウスホイールでも変えられます。"),
    "Follow member": ("멤버 따라가기", "メンバーを追う"),
    "While a member is the target, the free camera moves with that member as the MV plays or the playhead moves. Preview only.": (
        "멤버가 대상일 때 MV를 재생하거나 재생 위치를 옮기면 자유 카메라가 그 멤버와 함께 움직입니다. 미리보기 전용입니다.",
        "メンバーが対象のとき、MVの再生中や再生位置の移動に合わせて自由カメラがそのメンバーと一緒に動きます。プレビュー専用です。"),
}
for _source, (_korean, _japanese) in _MV_FREE_CAMERA_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# MV-only song registration (mv-studio-register.js, core/mv_studio_register.py): the panel, the
# job stages, the plan notes, every Elichika store message (mv_studio_live.MESSAGES), the CRI
# encoder's fixed messages and the native export refusals a registration can show.
_MV_REGISTER_TRANSLATIONS = {
    # Panel
    "Register as an MV-only song": ("MV 전용 곡으로 등록", "MV専用曲として登録"),
    "Update song": ("업데이트", "更新"),
    "Register as a new song": ("새 곡으로 등록", "新しい曲として登録"),
    "Base MV": ("기본 MV", "ベースMV"),
    "Choose base MV": ("기본 MV 고르기", "ベースMVを選ぶ"),
    "Change": ("변경", "変更"),
    "Stage, choreography, props and members come from the base MV.": (
        "무대·안무·소품·멤버는 기본 MV의 것을 사용합니다.", "ステージ・振り付け・小物・メンバーはベースMVのものを使います。"),
    "Title": ("제목", "タイトル"),
    "Credit": ("크레디트", "クレジット"),
    "Leave empty to use the base song's credit.": (
        "비워 두면 기본 MV 곡의 크레디트를 씁니다.", "空欄のままにするとベースMVの曲のクレジットを使います。"),
    "Jacket": ("재킷", "ジャケット"),
    "Choose image": ("이미지 선택", "画像を選択"),
    "Choose jacket image": ("재킷 이미지 선택", "ジャケット画像を選択"),
    "Use the base jacket": ("기본 재킷 사용", "ベースのジャケットを使う"),
    "Keep the registered jacket": ("등록된 재킷 유지", "登録済みのジャケットのまま"),
    "Choose the square area for the jacket.": ("재킷으로 쓸 정사각형 영역을 고르세요.", "ジャケットに使う正方形の範囲を選んでください。"),
    "Jacket area size": ("영역 크기", "範囲の大きさ"),
    "The selected area is used as is.": ("고른 영역을 그대로 씁니다.", "選んだ範囲をそのまま使います。"),
    "The selected area is resized to 400×400.": ("고른 영역을 400×400으로 크기만 맞춥니다.", "選んだ範囲を400×400に拡大・縮小します。"),
    "This 400×400 image is used as is.": ("400×400 이미지라 그대로 씁니다.", "400×400の画像なのでそのまま使います。"),
    "This square image is resized to 400×400.": ("정사각형 이미지를 400×400으로 크기만 맞춥니다.", "正方形の画像を400×400に拡大・縮小します。"),
    "The registered jacket stays.": ("등록된 재킷을 그대로 둡니다.", "登録済みのジャケットのままです。"),
    "The base song's jacket is used.": ("기본 MV 곡의 재킷을 씁니다.", "ベースMVの曲のジャケットを使います。"),
    "400×400 · choose an area when the image is not square.": (
        "400×400 · 정사각형이 아니면 영역을 고르세요.", "400×400・正方形でない画像は範囲を選んでください。"),
    "Audio": ("음원", "音源"),
    "Original song audio": ("원곡 음원 그대로", "原曲の音源のまま"),
    "Keep the registered audio": ("등록된 음원 유지", "登録済みの音源のまま"),
    "Project audio": ("프로젝트 음원", "プロジェクトの音源"),
    "Prepared ACB/AWB (advanced)": ("준비된 ACB/AWB 파일 (고급)", "用意したACB/AWBファイル（上級者向け）"),
    "This version can register only the original audio or prepared ACB/AWB files.": (
        "이 버전에서는 원곡 음원 또는 ACB/AWB 파일만 쓸 수 있습니다.", "このバージョンでは原曲の音源かACB/AWBファイルだけを使えます。"),
    "This project has no soundtrack.": ("이 프로젝트에는 음원이 없습니다.", "このプロジェクトには音源がありません。"),
    "BPM": ("BPM", "BPM"),
    "First beat (s)": ("첫 박 (초)", "最初の拍（秒）"),
    "Preview start (s)": ("미리듣기 시작 (초)", "試聴の開始（秒）"),
    "The soundtrack offset ({offset} s) is applied to the registered audio.": (
        "음원 오프셋({offset}초)을 등록할 음원에 반영합니다.", "音源オフセット（{offset}秒）を登録する音源に反映します。"),
    "What reaches the game": ("게임 반영 점검", "ゲームへの反映チェック"),
    "Timeline unchanged: the original MV plays.": ("타임라인 변경 없음: 원래 MV가 재생됩니다.", "タイムラインの変更なし：元のMVが再生されます。"),
    "No native timeline: the base MV's timeline plays unchanged.": (
        "게임용 타임라인이 없는 프로젝트라 기본 MV의 타임라인이 그대로 재생됩니다.",
        "ゲーム用タイムラインがないプロジェクトなので、ベースMVのタイムラインがそのまま再生されます。"),
    "Camera: {count} shots edited": ("카메라 {count}컷 수정", "カメラ{count}カットを編集"),
    "Camera: {count} shots edited (follow camera included)": (
        "카메라 {count}컷 수정 (팔로우 카메라 포함)", "カメラ{count}カットを編集（フォローカメラを含む）"),
    "Values: {values} · clip timing: {timing}": (
        "조명·효과 값 {values}개 · 클립 타이밍 {timing}개", "照明・効果の値{values}件・クリップのタイミング{timing}件"),
    "Applied on Android and iOS": ("Android · iOS 모두 적용", "AndroidとiOSの両方に反映"),
    "Applied on {platform}": ("{platform}에 적용", "{platform}に反映"),
    "Download (about {size} MB)": ("내려받기 (약 {size} MB)", "ダウンロード（約{size} MB）"),
    "No {platform} original": ("{platform} 원본 없음", "{platform}の元データなし"),
    "{platform} has no original in this region: it plays the base MV.": (
        "이 지역에는 {platform} 원본이 없어 기본 MV가 재생됩니다.", "この地域には{platform}の元データがないため、ベースMVが再生されます。"),
    "Not in the game:": ("게임에 들어가지 않음:", "ゲームには入らないもの："),
    "Checking what reaches the game…": ("게임 반영 점검 중…", "ゲームへの反映をチェック中…"),
    "Open this panel to check what reaches the game.": (
        "이 패널을 열면 게임에 반영되는 내용을 점검합니다.", "このパネルを開くとゲームに反映される内容をチェックします。"),
    "Region: {region}": ("지역: {region}", "地域：{region}"),
    "New song": ("새 곡", "新しい曲"),
    "Update {title} ({id})": ("{title} ({id}) 업데이트", "{title}（{id}）を更新"),
    "Register as": ("등록 대상", "登録先"),
    "Songs registered from this base MV: {songs}": ("이 기본 MV로 등록한 곡이 있습니다: {songs}", "このベースMVで登録した曲があります：{songs}"),
    "Not chosen": ("선택 안 함", "未選択"),
    "Search MV": ("MV 검색", "MVを検索"),
    "Use this base MV": ("이 MV를 기본 MV로 사용", "このMVをベースにする"),
    "Continue": ("계속", "続ける"),
    "iOS will play the original MV. Continue?": ("iOS에서는 원래 MV가 재생됩니다. 계속할까요?", "iOSでは元のMVが再生されます。続けますか？"),
    "Android will play the original MV. Continue?": (
        "Android에서는 원래 MV가 재생됩니다. 계속할까요?", "Androidでは元のMVが再生されます。続けますか？"),
    "Android and iOS will play the original MV. Continue?": (
        "Android와 iOS 모두 원래 MV가 재생됩니다. 계속할까요?", "AndroidとiOSの両方で元のMVが再生されます。続けますか？"),
    "Preparing the project": ("프로젝트 준비 중", "プロジェクトを準備中"),
    "Decoding the soundtrack": ("음원 읽는 중", "音源を読み込み中"),
    "Registered '{title}' ({id}).": ("'{title}'({id})를 등록했습니다.", "「{title}」（{id}）を登録しました。"),
    "Updated '{title}' ({id}).": ("'{title}'({id})를 업데이트했습니다.", "「{title}」（{id}）を更新しました。"),
    "Removed '{title}' ({id}).": ("'{title}'({id})를 삭제했습니다.", "「{title}」（{id}）を削除しました。"),
    "No changes to apply.": ("바뀐 내용이 없습니다.", "変更はありません。"),
    "The game server was restarted.": ("게임 서버를 다시 시작했습니다.", "ゲームサーバーを再起動しました。"),
    "The game server restarts when this job finishes.": ("작업이 끝나면 게임 서버를 다시 시작합니다.", "処理が終わるとゲームサーバーを再起動します。"),
    "Restart the game server to apply it.": ("게임 서버를 다시 시작해야 적용됩니다.", "反映するにはゲームサーバーを再起動してください。"),
    "The game server was stopped. Start it again.": ("게임 서버를 멈췄습니다. 다시 시작하세요.", "ゲームサーバーを停止しました。もう一度起動してください。"),
    "In game: Live → song list → {title} → MV": (
        "게임: 라이브 → 곡 목록 → {title} → MV 버튼", "ゲーム：ライブ → 楽曲一覧 → {title} → MVボタン"),
    "Registered MV-only songs ({count})": ("등록한 MV 전용 곡 ({count})", "登録したMV専用曲（{count}）"),
    "No MV-only songs are registered in this region.": ("이 지역에 등록한 MV 전용 곡이 없습니다.", "この地域に登録したMV専用曲はありません。"),
    "Updated {date}": ("{date} 수정", "{date} 更新"),
    "Not visible in the game (no Advanced chart)": ("게임에 보이지 않음 (상급 채보 없음)", "ゲームに表示されません（上級の譜面なし）"),
    "Base MV unknown": ("기본 MV를 알 수 없음", "ベースMVが不明"),
    "Original MV on iOS": ("iOS 원본 MV", "iOSは元のMV"),
    "Original MV on Android": ("Android 원본 MV", "Androidは元のMV"),
    "Open": ("열기", "開く"),
    "Fix": ("고치기", "修正"),
    "Delete": ("삭제", "削除"),
    "Delete '{title}'?": ("'{title}'를 삭제할까요?", "「{title}」を削除しますか？"),
    ("This deletes the song, its jacket, audio and timeline files, and every player's MV deck, play records and playlist "
     "entries for it. A backup is made first, and the game server stops for a moment."): (
        "곡, 재킷, 음원, 타임라인 파일과 모든 플레이어의 이 곡 MV 덱·플레이 기록·플레이리스트 항목을 지웁니다. "
        "지우기 전에 백업을 만들고, 게임 서버를 잠시 멈춥니다.",
        "曲、ジャケット、音源、タイムラインのファイルと、全プレイヤーのこの曲のMVデッキ・プレイ記録・プレイリスト項目を削除します。"
        "削除の前にバックアップを作り、ゲームサーバーを一時停止します。"),
    "Player records to delete: {count}": ("지울 플레이어 기록: {count}개", "削除するプレイヤー記録：{count}件"),
    "Advanced: replace charts": ("고급: 채보 바꾸기", "上級者向け：譜面の差し替え"),
    "Replace the placeholder Advanced chart with your own, or add other difficulties.": (
        "자리 표시용 상급 채보를 직접 만든 채보로 바꾸거나 다른 난이도를 추가합니다.",
        "仮の上級譜面を自作の譜面に差し替えたり、ほかの難易度を追加したりします。"),
    "This browser cannot open this audio format. Convert it to WAV and import it again.": (
        "이 브라우저에서 이 음원 형식을 열 수 없습니다. WAV로 바꿔서 가져오세요.",
        "このブラウザーではこの音源の形式を開けません。WAVに変換して読み込み直してください。"),
    "The project soundtrack is no longer available. Import it again.": (
        "프로젝트 음원을 더 이상 찾을 수 없습니다. 다시 가져오세요.", "プロジェクトの音源が見つかりません。読み込み直してください。"),
    "The soundtrack offset leaves no audio to register.": (
        "음원 오프셋 때문에 등록할 음원이 남지 않습니다.", "音源オフセットのため、登録する音源が残りません。"),
    "The converted audio is empty or larger than 96 MiB.": (
        "변환한 음원이 비어 있거나 96 MiB보다 큽니다.", "変換した音源が空か、96 MiBを超えています。"),
    "MV registration progress is unavailable. Reopen this page.": (
        "등록 진행 상황을 받을 수 없습니다. 이 페이지를 다시 여세요.", "登録の進行状況を受け取れません。このページを開き直してください。"),
    "MV registration progress was interrupted. Check the songs list.": (
        "등록 진행 상황이 끊겼습니다. 등록한 곡 목록을 확인하세요.", "登録の進行状況が途切れました。登録した曲の一覧を確認してください。"),
    "MV registration was cancelled.": ("MV 등록을 취소했습니다.", "MVの登録をキャンセルしました。"),
    "Removing the MV-only song was cancelled.": ("MV 전용 곡 삭제를 취소했습니다.", "MV専用曲の削除をキャンセルしました。"),
    "Some editor changes are not baked into the timeline yet. Wait for them to finish, then register again.": (
        "아직 타임라인에 반영되지 않은 편집이 있습니다. 끝날 때까지 기다린 뒤 다시 등록하세요.",
        "まだタイムラインに反映されていない編集があります。終わるまで待ってから登録し直してください。"),
    # Job stages
    "Checking the base MV originals": ("기본 MV 원본 확인", "ベースMVの元データを確認"),
    "Building the Android timeline": ("Android 타임라인 만드는 중", "Android用タイムラインを作成中"),
    "Building the iOS timeline": ("iOS 타임라인 만드는 중", "iOS用タイムラインを作成中"),
    "Converting the audio": ("음원 변환 중", "音源を変換中"),
    "Building the preview audio": ("미리듣기 음원 만드는 중", "試聴用の音源を作成中"),
    "Preparing the jacket": ("재킷 준비 중", "ジャケットを準備中"),
    "Stopping the game server": ("게임 서버 정지", "ゲームサーバーを停止"),
    "Writing to the game catalog": ("게임 목록에 쓰는 중", "ゲームの一覧に書き込み中"),
    "Restarting the game server": ("게임 서버 다시 시작", "ゲームサーバーを再起動"),
    "Removing the song from the game": ("게임에서 곡 지우는 중", "ゲームから曲を削除中"),
    # Plan notes and registration errors (core/mv_studio_register.py)
    "MV registration requires the Elichika server app.": (
        "MV 등록에는 Elichika 서버 앱이 필요합니다.", "MVの登録にはElichikaサーバーアプリが必要です。"),
    "Another MV registration or removal is running. Try again when it finishes.": (
        "다른 MV 등록이나 삭제가 진행 중입니다. 끝난 뒤 다시 시도하세요.",
        "ほかのMVの登録または削除を実行中です。終わってからもう一度お試しください。"),
    "Choose the base MV.": ("기본 MV를 고르세요.", "ベースMVを選んでください。"),
    "The base MV of this song is unknown. Only removal is available.": (
        "이 곡의 기본 MV를 알 수 없습니다. 삭제만 할 수 있습니다.", "この曲のベースMVが不明です。削除のみできます。"),
    ("The registered song this project was opened from was removed. Choose a stock base MV to register this "
     "project."): (
        "이 프로젝트를 연 등록 곡이 삭제되었습니다. 이 프로젝트를 등록하려면 게임의 원래 MV를 기본 MV로 고르세요.",
        "このプロジェクトを開いた登録済みの曲は削除されました。このプロジェクトを登録するには、ゲームの元のMVをベースMVとして選んでください。"),
    "This song was made from another base MV. Register the project as a new song.": (
        "이 곡은 다른 기본 MV로 만들었습니다. 이 프로젝트는 새 곡으로 등록하세요.",
        "この曲は別のベースMVから作られています。このプロジェクトは新しい曲として登録してください。"),
    "The track structure changed, so the timeline cannot go into the game:": (
        "트랙 구조가 바뀌어 게임에 넣을 수 없습니다:", "トラックの構成が変わったため、ゲームに入れられません："),
    "The original MV timeline is unavailable. Reopen the original timeline before saving.": (
        "원본 MV 타임라인을 찾을 수 없습니다. 원본 타임라인을 다시 연 뒤 저장하세요.",
        "元のMVタイムラインが見つかりません。元のタイムラインを開き直してから保存してください。"),
    "The project's timeline does not belong to this base MV.": (
        "프로젝트의 타임라인이 이 기본 MV의 것이 아닙니다.", "プロジェクトのタイムラインはこのベースMVのものではありません。"),
    "The base MV's original iOS timeline is not available. Allow the download, or register for Android only.": (
        "기본 MV의 iOS 원본 타임라인이 없습니다. 내려받기를 허용하거나 Android에만 등록하세요.",
        "ベースMVのiOS用の元タイムラインがありません。ダウンロードを許可するか、Androidだけに登録してください。"),
    "The base MV's original Android timeline is not available. Allow the download, or register for iOS only.": (
        "기본 MV의 Android 원본 타임라인이 없습니다. 내려받기를 허용하거나 iOS에만 등록하세요.",
        "ベースMVのAndroid用の元タイムラインがありません。ダウンロードを許可するか、iOSだけに登録してください。"),
    ("The edits could not be baked into the iOS original MV. Register for Android only to play the original MV on "
     "iOS."): (
        "편집 내용을 iOS 원본 MV에 넣지 못했습니다. iOS에서 원래 MV가 재생되도록 Android에만 등록하세요.",
        "編集内容をiOSの元のMVに反映できませんでした。iOSでは元のMVが再生されるよう、Androidだけに登録してください。"),
    ("The edits could not be baked into the Android original MV. Register for iOS only to play the original MV on "
     "Android."): (
        "편집 내용을 Android 원본 MV에 넣지 못했습니다. Android에서 원래 MV가 재생되도록 iOS에만 등록하세요.",
        "編集内容をAndroidの元のMVに反映できませんでした。Androidでは元のMVが再生されるよう、iOSだけに登録してください。"),
    "The Android and iOS timelines came out different, so nothing was registered.": (
        "Android와 iOS 타임라인이 서로 다르게 만들어져 등록하지 않았습니다.",
        "AndroidとiOSのタイムラインが異なる結果になったため、登録しませんでした。"),
    "The project changed after the last check. Check it again, then register.": (
        "마지막 점검 뒤에 프로젝트가 바뀌었습니다. 다시 점검한 다음 등록하세요.",
        "前回のチェックの後にプロジェクトが変わりました。もう一度チェックしてから登録してください。"),
    "{platform}: the registered timeline stays": ("{platform}: 등록된 타임라인을 그대로 둡니다", "{platform}：登録済みのタイムラインのままです"),
    "Register for Android only": ("Android에만 등록", "Androidだけに登録"),
    "Register for iOS only": ("iOS에만 등록", "iOSだけに登録"),
    "{platform}: left out of this registration, it plays the original MV": (
        "{platform}: 이번 등록에서 빠지며 원래 MV가 재생됩니다", "{platform}：今回の登録から外れ、元のMVが再生されます"),
    "Backup: {path}": ("백업: {path}", "バックアップ：{path}"),
    "Enter a song title between 1 and 160 characters.": ("곡 제목을 1~160자로 입력하세요.", "曲のタイトルを1〜160文字で入力してください。"),
    "Enter a credit of at most 200 characters on one line.": (
        "크레디트는 한 줄로 200자 이내로 입력하세요.", "クレジットは1行・200文字以内で入力してください。"),
    "Choose Android, iOS or both.": ("Android, iOS 또는 둘 다 고르세요.", "Android、iOS、または両方を選んでください。"),
    "The MV registration request is invalid.": ("MV 등록 요청이 올바르지 않습니다.", "MVの登録リクエストが正しくありません。"),
    "Choose a new song, or a registered song to update.": (
        "새 곡 또는 업데이트할 등록 곡을 고르세요.", "新しい曲か、更新する登録済みの曲を選んでください。"),
    "A new song has no registered part to keep.": ("새 곡에는 유지할 등록 내용이 없습니다.", "新しい曲には保持する登録内容がありません。"),
    "Choose the song audio.": ("곡 음원을 고르세요.", "曲の音源を選んでください。"),
    "Enter the BPM and the first beat of the project audio.": (
        "프로젝트 음원의 BPM과 첫 박을 입력하세요.", "プロジェクトの音源のBPMと最初の拍を入力してください。"),
    "Enter a BPM between 1 and 999 and a first beat of 0 seconds or more.": (
        "BPM은 1~999, 첫 박은 0초 이상으로 입력하세요.", "BPMは1〜999、最初の拍は0秒以上で入力してください。"),
    "Enter a preview start of 0 seconds or more.": ("미리듣기 시작은 0초 이상으로 입력하세요.", "試聴の開始は0秒以上で入力してください。"),
    "The converted project audio is no longer available. Register again.": (
        "변환한 프로젝트 음원을 더 이상 찾을 수 없습니다. 다시 등록하세요.",
        "変換したプロジェクトの音源が見つかりません。もう一度登録してください。"),
    "The base song's audio is not available locally. Allow the download, or keep the original audio.": (
        "기본 MV 곡의 음원이 이 기기에 없습니다. 내려받기를 허용하거나 원곡 음원을 그대로 쓰세요.",
        "ベースMVの曲の音源がこの端末にありません。ダウンロードを許可するか、原曲の音源のまま使ってください。"),
    "Choose the jacket.": ("재킷을 고르세요.", "ジャケットを選んでください。"),
    "The jacket area must be a square inside the image.": (
        "재킷 영역은 이미지 안의 정사각형이어야 합니다.", "ジャケットの範囲は画像内の正方形にしてください。"),
    "The jacket must be a PNG, JPEG or another image this app can open.": (
        "재킷은 PNG, JPEG 등 이 앱이 열 수 있는 이미지여야 합니다.", "ジャケットはPNGやJPEGなど、このアプリで開ける画像にしてください。"),
    "The jacket image is larger than this app can open.": (
        "재킷 이미지가 너무 커서 이 앱에서 열 수 없습니다.", "ジャケット画像が大きすぎて、このアプリでは開けません。"),
    "Track settings do not reach the game:": ("트랙 설정은 게임에 반영되지 않습니다:", "トラックの設定はゲームに反映されません："),
    "These edited values are preview-only:": ("이 편집 값은 미리보기에만 적용됩니다:", "これらの編集値はプレビューのみに反映されます："),
    "Imported stage, effect or prop models": ("가져온 무대·효과·소품 모델", "読み込んだステージ・エフェクト・小物のモデル"),
    "Imported performer models": ("가져온 출연자 모델", "読み込んだ出演者のモデル"),
    "Member positions": ("멤버 위치", "メンバーの位置"),
    "Pinned costumes (choose outfits in the game's MV deck)": (
        "의상 고정 (의상은 게임의 MV 덱에서 고르세요)", "衣装の固定（衣装はゲームのMVデッキで選んでください）"),
    "MV quality preview settings": ("MV 그래픽 미리보기 설정", "MVグラフィックのプレビュー設定"),
    "Editor changes that could not be baked:": ("타임라인에 반영하지 못한 편집:", "タイムラインに反映できなかった編集："),
    "The follow camera is baked for the preview members' heights.": (
        "팔로우 카메라는 미리보기 멤버 키 기준으로 만들어집니다.", "フォローカメラはプレビューのメンバーの身長を基準に作られます。"),
    "The audio is {seconds} s longer than the MV. The last scene holds until the music ends.": (
        "음원이 MV보다 {seconds}초 깁니다. 마지막 장면이 멈춘 채로 끝까지 재생됩니다.",
        "音源がMVより{seconds}秒長いです。最後の場面が止まったまま最後まで再生されます。"),
    "The audio is {seconds} s shorter than the MV. The MV ends with the music.": (
        "음원이 MV보다 {seconds}초 짧습니다. 음원이 끝나면 MV도 끝납니다.", "音源がMVより{seconds}秒短いです。音源が終わるとMVも終わります。"),
    "The soundtrack offset applies only to the project audio. The original audio starts with the MV.": (
        "음원 오프셋은 프로젝트 음원에만 적용됩니다. 원곡 음원은 MV와 함께 시작합니다.",
        "音源オフセットはプロジェクトの音源にだけ反映されます。原曲の音源はMVと同時に始まります。"),
    "The edits are counted once the original MV is available. Allow the download to bake them.": (
        "원본 MV를 받은 뒤 편집을 셉니다. 반영하려면 내려받기를 허용하세요.",
        "元のMVを取得してから編集を数えます。反映するにはダウンロードを許可してください。"),
    # Registration routes (webtools/server.py)
    "Send the converted audio as a WAV file.": ("변환한 음원을 WAV 파일로 보내세요.", "変換した音源をWAVファイルとして送ってください。"),
    "The converted audio upload was interrupted.": ("변환한 음원 업로드가 중간에 끊겼습니다.", "変換した音源のアップロードが途中で途切れました。"),
    "Open 3D MV at the local app address before changing the game catalog.": (
        "게임 목록을 바꾸려면 이 기기의 앱 주소에서 3D MV를 여세요.",
        "ゲームの一覧を変更するには、この端末のアプリのアドレスで3D MVを開いてください。"),
    "Open the editor from this app before saving changes.": (
        "변경 내용을 저장하려면 이 앱에서 편집기를 여세요.", "変更を保存するには、このアプリからエディターを開いてください。"),
    "The MV request failed.": ("MV 요청에 실패했습니다.", "MVのリクエストに失敗しました。"),
    "Invalid editing request size.": ("편집 요청 크기가 올바르지 않습니다.", "編集リクエストのサイズが正しくありません。"),
    "The editing request is too large or empty.": ("편집 요청이 너무 크거나 비어 있습니다.", "編集リクエストが大きすぎるか、空です。"),
    "Unsupported editing request.": ("지원하지 않는 편집 요청입니다.", "対応していない編集リクエストです。"),
    "Choose a valid MV search.": ("올바른 MV 검색어를 입력하세요.", "正しいMVの検索条件を入力してください。"),
    "Provide a matching chart and difficulty template.": (
        "맞는 채보와 난이도 템플릿을 넣어 주세요.", "対応する譜面と難易度テンプレートを指定してください。"),
    "Database maintenance is busy. Retry after the current operation finishes.": (
        "다른 데이터베이스 작업이 진행 중입니다. 끝난 뒤 다시 시도하세요.",
        "ほかのデータベース処理を実行中です。終わってからもう一度お試しください。"),
    "Database maintenance could not start safely. Retry after checking the runtime.": (
        "데이터베이스 작업을 안전하게 시작하지 못했습니다. 실행 환경을 확인한 뒤 다시 시도하세요.",
        "データベース処理を安全に開始できませんでした。実行環境を確認してからもう一度お試しください。"),
    # Native export refusals (core/mv_studio_timeline.py)
    "Native export can edit existing tracks in their original order only.": (
        "게임용 내보내기는 기존 트랙을 원래 순서 그대로만 편집할 수 있습니다.",
        "ゲーム用の書き出しでは、既存のトラックを元の順番のまま編集することしかできません。"),
    "Track identity, binding, and original metadata are read-only in native exports.": (
        "게임용 내보내기에서 트랙 식별자, 연결 대상, 원래 메타데이터는 바꿀 수 없습니다.",
        "ゲーム用の書き出しでは、トラックの識別子・バインド先・元のメタデータは変更できません。"),
    "Native export can edit existing clip slots in their original order only.": (
        "게임용 내보내기는 기존 클립 칸을 원래 순서 그대로만 편집할 수 있습니다.",
        "ゲーム用の書き出しでは、既存のクリップ枠を元の順番のまま編集することしかできません。"),
    "The revision cannot replace a native clip's original identities or fields.": (
        "편집으로 원래 클립의 식별자나 필드를 바꿀 수 없습니다.", "編集で元のクリップの識別子やフィールドを置き換えることはできません。"),
    "The revision cannot change which native clip fields are editable.": (
        "편집으로 원래 클립의 편집 가능한 필드를 바꿀 수 없습니다.", "編集で元のクリップの編集可能なフィールドを変えることはできません。"),
    "Change the original clip timings to set the native timeline duration.": (
        "게임용 타임라인 길이를 바꾸려면 원래 클립의 타이밍을 바꾸세요.",
        "ゲーム用タイムラインの長さを変えるには、元のクリップのタイミングを変えてください。"),
    "An edited clip uses a shared or external playable asset. Edit its timing only.": (
        "편집한 클립이 공유되거나 외부에 있는 재생 에셋을 씁니다. 타이밍만 편집하세요.",
        "編集したクリップは共有または外部の再生アセットを使っています。タイミングだけを編集してください。"),
    "This camera animation is shared or external. Edit its timing only.": (
        "이 카메라 애니메이션은 공유되거나 외부에 있습니다. 타이밍만 편집하세요.",
        "このカメラアニメーションは共有または外部のものです。タイミングだけを編集してください。"),
    "Keep one camera point per frame of the shot, at its frame times.": (
        "샷의 프레임마다 카메라 포인트를 하나씩, 그 프레임 시간에 두세요.",
        "ショットのフレームごとにカメラポイントを1つずつ、そのフレームの時刻に置いてください。"),
    "Camera point edits need an untrimmed native shot: clip offset 0, speed 1 and its own camera bindings.": (
        "카메라 포인트를 편집하려면 잘리지 않은 원래 샷이어야 합니다: 클립 오프셋 0, 속도 1, 원래 카메라 바인딩.",
        "カメラポイントを編集するには、切り詰めていない元のショットが必要です（クリップオフセット0、速度1、元のカメラバインディング）。"),
    "A camera shot with camera edits needs a length of whole frames (1/60 s).": (
        "카메라를 편집한 샷의 길이는 프레임(1/60초) 단위여야 합니다.", "カメラを編集したショットの長さは、フレーム（1/60秒）単位にしてください。"),
    "The native copy changed unrelated Unity objects or resources.": (
        "게임용 사본에서 관계없는 Unity 오브젝트나 리소스가 바뀌었습니다.",
        "ゲーム用のコピーで無関係なUnityオブジェクトまたはリソースが変わりました。"),
    "A native timeline edit did not survive serialization.": (
        "게임용 타임라인 편집이 저장 과정에서 유지되지 않았습니다.", "ゲーム用タイムラインの編集が保存の過程で保たれませんでした。"),
    "Timeline diagnostics are read-only in native exports.": (
        "게임용 내보내기에서 타임라인 진단 정보는 바꿀 수 없습니다.", "ゲーム用の書き出しでは、タイムラインの診断情報は変更できません。"),
    "The revision no longer matches the original timeline.": (
        "편집 내용이 원래 타임라인과 더 이상 맞지 않습니다.", "編集内容が元のタイムラインと一致しなくなりました。"),
    # Elichika store (mv_studio_live.MESSAGES)
    "Choose a native file of the expected type.": ("올바른 형식의 게임 파일을 고르세요.", "正しい形式のゲーム用ファイルを選んでください。"),
    "The selected file is empty, too large or unreadable.": (
        "선택한 파일이 비어 있거나 너무 크거나 읽을 수 없습니다.", "選んだファイルが空か、大きすぎるか、読み込めません。"),
    "The selected file changed during registration. Try again.": (
        "등록하는 동안 선택한 파일이 바뀌었습니다. 다시 시도하세요.", "登録中に選んだファイルが変わりました。もう一度お試しください。"),
    "Provide each native timeline as an unpacked UnityFS bundle.": (
        "게임용 타임라인은 압축을 푼 UnityFS 번들로 넣어 주세요.", "ゲーム用タイムラインは展開済みのUnityFSバンドルで指定してください。"),
    "The native timeline exceeds the supported file size.": (
        "게임용 타임라인이 지원하는 파일 크기를 넘습니다.", "ゲーム用タイムラインが対応するファイルサイズを超えています。"),
    "The jacket must be a PNG or JPEG image of exactly 400x400 pixels.": (
        "재킷은 정확히 400x400 픽셀인 PNG 또는 JPEG 이미지여야 합니다.", "ジャケットはちょうど400x400ピクセルのPNGまたはJPEG画像にしてください。"),
    "The jacket image must be at most 2 MiB.": ("재킷 이미지는 2 MiB 이하여야 합니다.", "ジャケット画像は2 MiB以下にしてください。"),
    "Provide the song audio as an ACB cue sheet with its optional AWB bank.": (
        "곡 음원은 ACB 큐 시트와 (필요하면) AWB 뱅크로 넣어 주세요.", "曲の音源はACBキューシートと（必要なら）AWBバンクで指定してください。"),
    "The audio cue sheet or bank is empty or too large.": (
        "음원 큐 시트나 뱅크가 비어 있거나 너무 큽니다.", "音源のキューシートまたはバンクが空か、大きすぎます。"),
    "Provide an ACB containing one playable cue with the same name as the sheet.": (
        "시트와 같은 이름의 재생 가능한 큐가 하나 든 ACB를 넣어 주세요.", "シートと同じ名前の再生できるキューが1つ入ったACBを指定してください。"),
    "Provide the matching AWB for a streaming cue, or only the ACB for an embedded cue.": (
        "스트리밍 큐에는 짝이 맞는 AWB를, 내장 큐에는 ACB만 넣어 주세요.",
        "ストリーミングのキューには対応するAWBを、埋め込みのキューにはACBだけを指定してください。"),
    "The audio cue could not be read or decoded.": ("음원 큐를 읽거나 디코딩하지 못했습니다.", "音源のキューを読み込めないか、デコードできませんでした。"),
    "Choose the ACB cue sheet for this AWB bank.": ("이 AWB 뱅크의 ACB 큐 시트를 고르세요.", "このAWBバンクに対応するACBキューシートを選んでください。"),
    "The CRI sheet must use an unused music_XXXX game cue name.": (
        "CRI 시트 이름은 쓰이지 않은 music_XXXX 게임 큐 이름이어야 합니다.", "CRIシート名は未使用のmusic_XXXX形式のゲームのキュー名にしてください。"),
    "The timeline must use the native format of its selected platform.": (
        "타임라인은 선택한 플랫폼의 게임 형식이어야 합니다.", "タイムラインは選んだプラットフォームのゲーム形式にしてください。"),
    "The selected Unity file has no unique native timeline container.": (
        "선택한 Unity 파일에 게임용 타임라인 컨테이너가 하나만 있지 않습니다.",
        "選んだUnityファイルにゲーム用タイムラインのコンテナーが1つだけではありません。"),
    "The selected Unity timeline container is empty.": ("선택한 Unity 타임라인 컨테이너가 비어 있습니다.", "選んだUnityタイムラインのコンテナーが空です。"),
    "The native timeline and its dependencies must match the selected stage template.": (
        "게임용 타임라인과 그 의존 파일이 선택한 기본 무대와 맞아야 합니다.",
        "ゲーム用タイムラインとその依存ファイルは、選んだベースのステージと一致する必要があります。"),
    "The timeline changes a serialized game type used by the stage.": (
        "타임라인이 무대가 쓰는 게임 데이터 형식을 바꿉니다.", "タイムラインがステージで使うゲームのデータ形式を変えています。"),
    "The timeline changes native container, script or resource data.": (
        "타임라인이 게임 컨테이너, 스크립트 또는 리소스 데이터를 바꿉니다.", "タイムラインがゲームのコンテナー・スクリプト・リソースのデータを変えています。"),
    "The timeline introduces a reference outside the selected stage template.": (
        "타임라인이 선택한 기본 무대 밖을 참조합니다.", "タイムラインが選んだベースのステージの外を参照しています。"),
    "The native Unity timeline could not be read against the selected stage template.": (
        "게임용 Unity 타임라인을 선택한 기본 무대와 비교해 읽지 못했습니다.",
        "ゲーム用Unityタイムラインを、選んだベースのステージと照らし合わせて読み込めませんでした。"),
    "A game catalog is missing the base MV's native timeline pack.": (
        "게임 목록에 기본 MV의 타임라인 팩이 없습니다.", "ゲームの一覧にベースMVのタイムラインパックがありません。"),
    "Install the base MV's original timeline for this platform locally, or allow the download, to verify the edit.": (
        "편집을 확인하려면 이 플랫폼의 기본 MV 원본 타임라인을 기기에 받아 두거나 내려받기를 허용하세요.",
        "編集を確認するには、このプラットフォーム用のベースMVの元タイムラインを端末に用意するか、ダウンロードを許可してください。"),
    "The supplied original timeline does not match the base MV's catalogued size.": (
        "받은 원본 타임라인이 게임 목록에 적힌 기본 MV의 크기와 다릅니다.",
        "取得した元タイムラインが、ゲームの一覧にあるベースMVのサイズと一致しません。"),
    "Provide a native timeline for Android, iOS or both.": (
        "Android, iOS 또는 둘 다의 게임용 타임라인을 넣어 주세요.", "Android、iOS、または両方のゲーム用タイムラインを指定してください。"),
    "A game catalog is missing the base MV's native timeline.": (
        "게임 목록에 기본 MV의 타임라인이 없습니다.", "ゲームの一覧にベースMVのタイムラインがありません。"),
    "Select the GL or JP catalog.": ("GL 또는 JP 목록을 고르세요.", "GLまたはJPの一覧を選んでください。"),
    "The region's game databases are incomplete.": ("이 지역의 게임 데이터베이스가 완전하지 않습니다.", "この地域のゲームデータベースがそろっていません。"),
    "Close the database editor so MV Studio can update all catalogs in one transaction.": (
        "MV 스튜디오가 모든 목록을 한 번에 고칠 수 있도록 데이터베이스 편집기를 닫으세요.",
        "MVスタジオがすべての一覧を一度に更新できるよう、データベースエディターを閉じてください。"),
    "The installed game database layout does not support this MV.": (
        "설치된 게임 데이터베이스 구조가 이 MV를 지원하지 않습니다.", "インストール済みのゲームデータベースの構造がこのMVに対応していません。"),
    "Stop the game server before removing an MV-only song.": (
        "MV 전용 곡을 지우기 전에 게임 서버를 멈추세요.", "MV専用曲を削除する前にゲームサーバーを停止してください。"),
    "Provide the original timelines per platform.": ("원본 타임라인을 플랫폼별로 넣어 주세요.", "元のタイムラインをプラットフォームごとに指定してください。"),
    "Name the preview cue sheet after the music cue sheet with _SABI.": (
        "미리듣기 큐 시트 이름은 음악 큐 시트 이름 뒤에 _SABI를 붙이세요.", "試聴用キューシートの名前は、曲のキューシート名の後ろに_SABIを付けてください。"),
    "Fingerprints must be short text values for android, ios, audio or jacket.": (
        "지문 값은 android, ios, audio, jacket용 짧은 문자열이어야 합니다.", "フィンガープリントはandroid・ios・audio・jacket用の短い文字列にしてください。"),
    "The MV-only song ID is outside this region's range.": (
        "MV 전용 곡 ID가 이 지역의 범위를 벗어납니다.", "MV専用曲のIDがこの地域の範囲外です。"),
    "No free MV-only song ID is left in this region.": ("이 지역에 남은 MV 전용 곡 ID가 없습니다.", "この地域で使えるMV専用曲のIDが残っていません。"),
    "The base MV must be a stock 3D song with a song cue and formation.": (
        "기본 MV는 곡 음원과 멤버 구성이 있는 게임 원래의 3D 곡이어야 합니다.",
        "ベースMVは、曲の音源とメンバー編成があるゲーム本来の3D曲にしてください。"),
    "Choose a stock game MV as the base, not a registered MV-only song.": (
        "기본 MV로는 등록한 MV 전용 곡이 아닌 게임 원래의 MV를 고르세요.",
        "ベースMVには、登録したMV専用曲ではなくゲーム本来のMVを選んでください。"),
    "The selected 3D timeline does not belong to the base song.": (
        "선택한 3D 타임라인이 기본 곡의 것이 아닙니다.", "選んだ3Dタイムラインはベースの曲のものではありません。"),
    "An MV position refers to an unknown stage.": ("MV 위치가 알 수 없는 무대를 가리킵니다.", "MVの位置が不明なステージを指しています。"),
    "Select a song registered by MV Studio.": ("MV 스튜디오로 등록한 곡을 고르세요.", "MVスタジオで登録した曲を選んでください。"),
    "A game catalog is missing a complete package of the base MV.": (
        "게임 목록에 기본 MV의 패키지가 온전히 있지 않습니다.", "ゲームの一覧にベースMVのパッケージがそろっていません。"),
    "A game catalog is missing its main package.": ("게임 목록에 main 패키지가 없습니다.", "ゲームの一覧にmainパッケージがありません。"),
    "A game catalog is missing the base song's native cue sheet.": (
        "게임 목록에 기본 곡의 큐 시트가 없습니다.", "ゲームの一覧にベースの曲のキューシートがありません。"),
    "The new audio must keep the song's existing cue sheet names.": (
        "새 음원은 곡의 기존 큐 시트 이름을 그대로 써야 합니다.", "新しい音源は曲の既存のキューシート名をそのまま使う必要があります。"),
    "The selected music ID or cue already belongs to a song in this region.": (
        "선택한 음악 ID나 큐를 이 지역의 다른 곡이 이미 쓰고 있습니다.", "選んだ音楽IDまたはキューは、この地域のほかの曲がすでに使っています。"),
    "The chart template has more stage effects than MV Studio can copy.": (
        "채보 템플릿의 스테이지 효과가 MV 스튜디오가 복사할 수 있는 수보다 많습니다.",
        "譜面テンプレートのステージ効果が、MVスタジオでコピーできる数より多いです。"),
    "The song's placeholder chart ID is already in use.": (
        "이 곡의 자리 표시용 채보 ID를 이미 쓰고 있습니다.", "この曲の仮の譜面IDはすでに使われています。"),
    "No playable Advanced chart was found to use as this song's placeholder.": (
        "이 곡의 자리 표시용으로 쓸 수 있는 상급 채보를 찾지 못했습니다.", "この曲の仮の譜面として使える上級の譜面が見つかりませんでした。"),
    "The placeholder chart template could not be read.": ("자리 표시용 채보 템플릿을 읽지 못했습니다.", "仮の譜面テンプレートを読み込めませんでした。"),
    "The requested MV-only song ID is already in use.": ("요청한 MV 전용 곡 ID를 이미 쓰고 있습니다.", "指定したMV専用曲のIDはすでに使われています。"),
    "Choose the update options explicitly.": ("업데이트 옵션을 직접 고르세요.", "更新のオプションを明示的に選んでください。"),
    "The registered song is incomplete in the game catalog. Remove it and register again.": (
        "등록한 곡이 게임 목록에 온전히 있지 않습니다. 삭제한 뒤 다시 등록하세요.",
        "登録した曲がゲームの一覧にそろっていません。削除してから登録し直してください。"),
    "The removal review is out of date. Review the song again before removing it.": (
        "삭제 확인 내용이 오래되었습니다. 곡을 다시 확인한 뒤 삭제하세요.", "削除の確認内容が古くなっています。曲をもう一度確認してから削除してください。"),
    "A live in progress uses this song. Finish the live in the game, then try again.": (
        "플레이 중인 라이브가 이 곡을 쓰고 있습니다. 게임에서 라이브를 끝낸 뒤 다시 시도하세요.",
        "プレイ中のライブがこの曲を使っています。ゲームでライブを終えてから、もう一度お試しください。"),
    "A profile showcase or ranking uses this song. Change it to another song in the game, then try again.": (
        "프로필 쇼케이스나 랭킹이 이 곡을 쓰고 있습니다. 게임에서 다른 곡으로 바꾼 뒤 다시 시도하세요.",
        "プロフィールの展示またはランキングがこの曲を使っています。ゲームでほかの曲に変えてから、もう一度お試しください。"),
    ("The song was removed, but players' records for it could not be cleaned. The game ignores records of songs it no "
     "longer has."): (
        "곡은 지웠지만 플레이어 기록을 정리하지 못했습니다. 게임은 없는 곡의 기록을 무시합니다.",
        "曲は削除しましたが、プレイヤーの記録を整理できませんでした。ゲームは存在しない曲の記録を無視します。"),
    ("The change was saved, but some files it no longer needs could not be moved or deleted. The game does not use "
     "them."): (
        "변경은 저장했지만 더는 필요 없는 일부 파일을 옮기거나 지우지 못했습니다. 게임은 이 파일을 쓰지 않습니다.",
        "変更は保存しましたが、不要になった一部のファイルを移動または削除できませんでした。ゲームはこれらのファイルを使いません。"),
    "The change was saved, but older MV Studio backups could not be deleted.": (
        "변경은 저장했지만 오래된 MV 스튜디오 백업을 지우지 못했습니다.", "変更は保存しましたが、古いMVスタジオのバックアップを削除できませんでした。"),
    "Choose the exact source stage before installing a replacement timeline.": (
        "대체 타임라인을 넣기 전에 원본 무대를 정확히 고르세요.", "差し替えタイムラインを入れる前に、元のステージを正確に選んでください。"),
    "The chart exceeds the supported file size.": ("채보가 지원하는 파일 크기를 넘습니다.", "譜面が対応するファイルサイズを超えています。"),
    "Provide a complete native stage chart, with its own note list.": (
        "노트 목록이 들어 있는 완전한 게임용 채보를 넣어 주세요.", "ノーツの一覧を含む完全なゲーム用譜面を指定してください。"),
    "The native chart must contain complete notes.": ("게임용 채보에 노트가 온전히 들어 있어야 합니다.", "ゲーム用譜面には完全なノーツが必要です。"),
    "The native chart contains invalid appeal chances.": ("게임용 채보에 잘못된 어필 찬스가 있습니다.", "ゲーム用譜面に不正なアピールチャンスがあります。"),
    "The native chart contains invalid note effects.": ("게임용 채보에 잘못된 노트 효과가 있습니다.", "ゲーム用譜面に不正なノーツ効果があります。"),
    "The native chart contains invalid stage effects.": ("게임용 채보에 잘못된 스테이지 효과가 있습니다.", "ゲーム用譜面に不正なステージ効果があります。"),
    "The native chart repeats an appeal chance or effect ID.": (
        "게임용 채보에 어필 찬스나 효과 ID가 중복됩니다.", "ゲーム用譜面でアピールチャンスまたは効果のIDが重複しています。"),
    "A chart note has an invalid timing, value or reference.": (
        "채보 노트의 타이밍, 값 또는 참조가 잘못되었습니다.", "譜面のノーツのタイミング・値・参照が正しくありません。"),
    "Provide one or more native chart files.": ("게임용 채보 파일을 하나 이상 넣어 주세요.", "ゲーム用譜面ファイルを1つ以上指定してください。"),
    "Choose a game difficulty type for each chart.": ("채보마다 게임 난이도를 고르세요.", "譜面ごとにゲームの難易度を選んでください。"),
    "A native chart needs a file and a gameplay template.": (
        "게임용 채보에는 파일과 게임 플레이 템플릿이 필요합니다.", "ゲーム用譜面にはファイルとゲームプレイのテンプレートが必要です。"),
    "Select an open gameplay template of the same difficulty type.": (
        "같은 난이도의 열려 있는 게임 플레이 템플릿을 고르세요.", "同じ難易度の、開放済みのゲームプレイテンプレートを選んでください。"),
    "A chart is already installed for that difficulty.": ("그 난이도에는 이미 채보가 들어 있습니다.", "その難易度にはすでに譜面が入っています。"),
    "The stock game requires a type-30 chart to open the song's MV from its music list.": (
        "게임 원래 클라이언트는 곡 목록에서 MV를 열려면 상급(30) 채보가 필요합니다.",
        "ゲーム本来のクライアントでは、楽曲一覧からMVを開くには上級（30）の譜面が必要です。"),
    "The gameplay template is missing its difficulty settings.": (
        "게임 플레이 템플릿에 난이도 설정이 없습니다.", "ゲームプレイテンプレートに難易度の設定がありません。"),
    "No free chart ID is left for that difficulty.": ("그 난이도에 쓸 수 있는 채보 ID가 남지 않았습니다.", "その難易度で使える譜面IDが残っていません。"),
    # CRI HCA encoder and ACB/AWB writer (core/cri_hca_encode.py, core/cri_acb_write.py)
    "The encoder needs 16-bit stereo PCM samples.": ("인코더에는 16비트 스테레오 PCM 샘플이 필요합니다.", "エンコーダーには16ビットのステレオPCMサンプルが必要です。"),
    "The decoded audio does not have the input's length and channels.": (
        "디코딩한 음원의 길이나 채널 수가 입력과 다릅니다.", "デコードした音源の長さまたはチャンネル数が入力と一致しません。"),
    "The PCM samples must be int16 with shape (frames, channels).": (
        "PCM 샘플은 (프레임, 채널) 모양의 int16이어야 합니다.", "PCMサンプルは(フレーム, チャンネル)の形のint16にしてください。"),
    "The HCA key must be a nonzero 64-bit value.": ("HCA 키는 0이 아닌 64비트 값이어야 합니다.", "HCAキーは0以外の64ビット値にしてください。"),
    "The HCA stream has no complete header.": ("HCA 스트림에 온전한 헤더가 없습니다.", "HCAストリームに完全なヘッダーがありません。"),
    "The HCA stream has no HCA header.": ("HCA 스트림에 HCA 헤더가 없습니다.", "HCAストリームにHCAヘッダーがありません。"),
    "The HCA header is truncated or fails its checksum.": (
        "HCA 헤더가 잘렸거나 체크섬이 맞지 않습니다.", "HCAヘッダーが途中で切れているか、チェックサムが一致しません。"),
    "The HCA header has no format or compression chunk.": (
        "HCA 헤더에 형식 또는 압축 청크가 없습니다.", "HCAヘッダーにフォーマットまたは圧縮のチャンクがありません。"),
    "The HCA header has no channels, sample rate or frame size.": (
        "HCA 헤더에 채널 수, 샘플레이트 또는 프레임 크기가 없습니다.", "HCAヘッダーにチャンネル数・サンプルレート・フレームサイズがありません。"),
    "The HCA encoder could not fit a frame.": ("HCA 인코더가 프레임을 크기에 맞추지 못했습니다.", "HCAエンコーダーがフレームを収められませんでした。"),
    "The HCA encoder overflowed a frame.": ("HCA 인코더의 프레임이 넘쳤습니다.", "HCAエンコーダーのフレームがあふれました。"),
    "The audio is empty or longer than the encoder limit.": ("음원이 비어 있거나 인코더 한도보다 깁니다.", "音源が空か、エンコーダーの上限より長いです。"),
    "The HCA key or bank subkey is invalid.": ("HCA 키 또는 뱅크 보조 키가 올바르지 않습니다.", "HCAキーまたはバンクのサブキーが正しくありません。"),
    "The encode progress callback is not callable.": ("인코딩 진행 콜백을 호출할 수 없습니다.", "エンコードの進捗コールバックを呼び出せません。"),
    "The WAV data must be bytes.": ("WAV 데이터는 바이트여야 합니다.", "WAVデータはバイト列にしてください。"),
    "The WAV file is empty or larger than the upload limit.": (
        "WAV 파일이 비어 있거나 업로드 한도보다 큽니다.", "WAVファイルが空か、アップロードの上限を超えています。"),
    "The file is not a complete RIFF/WAVE file.": ("온전한 RIFF/WAVE 파일이 아닙니다.", "完全なRIFF/WAVEファイルではありません。"),
    "The WAV file has no format or data chunk.": ("WAV 파일에 형식 또는 데이터 청크가 없습니다.", "WAVファイルにフォーマットまたはデータのチャンクがありません。"),
    "The WAV format chunk has an unsupported size.": ("WAV 형식 청크의 크기를 지원하지 않습니다.", "WAVのフォーマットチャンクのサイズに対応していません。"),
    "The WAV file is not 16-bit integer PCM.": ("WAV 파일이 16비트 정수 PCM이 아닙니다.", "WAVファイルが16ビット整数PCMではありません。"),
    "The WAV file has the wrong sample rate or channel count.": (
        "WAV 파일의 샘플레이트나 채널 수가 맞지 않습니다.", "WAVファイルのサンプルレートまたはチャンネル数が正しくありません。"),
    "The WAV format chunk is inconsistent.": ("WAV 형식 청크의 내용이 서로 맞지 않습니다.", "WAVのフォーマットチャンクの内容が矛盾しています。"),
    "The WAV data is empty or ends inside a sample.": (
        "WAV 데이터가 비어 있거나 샘플 중간에서 끝납니다.", "WAVデータが空か、サンプルの途中で終わっています。"),
    "The preview start must be a time inside the song.": ("미리듣기 시작은 곡 안의 시간이어야 합니다.", "試聴の開始は曲の範囲内の時間にしてください。"),
    "The preview fade must be zero or more seconds.": ("미리듣기 페이드는 0초 이상이어야 합니다.", "試聴のフェードは0秒以上にしてください。"),
    "The preview length must be a positive sample count.": ("미리듣기 길이는 양수 샘플 수여야 합니다.", "試聴の長さは正のサンプル数にしてください。"),
    "The HCA header has an unsupported chunk.": ("HCA 헤더에 지원하지 않는 청크가 있습니다.", "HCAヘッダーに対応していないチャンクがあります。"),
    "The HCA bitrate is too low for this audio.": ("이 음원에는 HCA 비트레이트가 너무 낮습니다.", "この音源にはHCAのビットレートが低すぎます。"),
    "The WAV file has a truncated chunk.": ("WAV 파일의 청크가 잘렸습니다.", "WAVファイルのチャンクが途中で切れています。"),
    "The WAV file must be 44100 Hz stereo.": ("WAV 파일은 44100 Hz 스테레오여야 합니다.", "WAVファイルは44100 Hzのステレオにしてください。"),
    "The WAV file has a misplaced format chunk.": ("WAV 파일의 형식 청크 위치가 잘못되었습니다.", "WAVファイルのフォーマットチャンクの位置が正しくありません。"),
    "The WAV file has a misplaced data chunk.": ("WAV 파일의 데이터 청크 위치가 잘못되었습니다.", "WAVファイルのデータチャンクの位置が正しくありません。"),
    "The reference PCM must be int16 with shape (samples, channels).": (
        "기준 PCM은 (샘플, 채널) 모양의 int16이어야 합니다.", "基準のPCMは(サンプル, チャンネル)の形のint16にしてください。"),
    "The cue sheet has no CRI UTF table.": ("큐 시트에 CRI UTF 테이블이 없습니다.", "キューシートにCRI UTFテーブルがありません。"),
    "The cue sheet contains invalid table bounds.": ("큐 시트의 테이블 범위가 잘못되었습니다.", "キューシートのテーブル範囲が正しくありません。"),
    "The cue sheet has an inconsistent row layout.": ("큐 시트의 행 구조가 서로 맞지 않습니다.", "キューシートの行の構造が矛盾しています。"),
    "BPM and the first beat are required for the cue's beat table.": (
        "큐의 비트 테이블을 만들려면 BPM과 첫 박이 필요합니다.", "キューのビートテーブルにはBPMと最初の拍が必要です。"),
    "The beat table needs a supported time signature.": ("비트 테이블에는 지원하는 박자가 필요합니다.", "ビートテーブルには対応している拍子が必要です。"),
    "The preview excerpt must lie inside the song.": ("미리듣기 구간은 곡 안에 있어야 합니다.", "試聴の区間は曲の範囲内にしてください。"),
    "The cue sheet name is invalid.": ("큐 시트 이름이 올바르지 않습니다.", "キューシート名が正しくありません。"),
    "The cue sheet GUID must be 16 bytes.": ("큐 시트 GUID는 16바이트여야 합니다.", "キューシートのGUIDは16バイトにしてください。"),
    "The HCA stream length does not match its header.": ("HCA 스트림 길이가 헤더와 맞지 않습니다.", "HCAストリームの長さがヘッダーと一致しません。"),
    "The HCA stream has no samples.": ("HCA 스트림에 샘플이 없습니다.", "HCAストリームにサンプルがありません。"),
    "The template cue sheet must hold exactly one cue with one waveform.": (
        "템플릿 큐 시트에는 파형 하나짜리 큐가 정확히 하나 있어야 합니다.",
        "テンプレートのキューシートには、波形が1つのキューがちょうど1つ必要です。"),
    "The template cue is not HCA audio.": ("템플릿 큐가 HCA 음원이 아닙니다.", "テンプレートのキューがHCA音源ではありません。"),
    "The template cue uses an unsupported streaming mode.": (
        "템플릿 큐가 지원하지 않는 스트리밍 방식을 씁니다.", "テンプレートのキューが対応していないストリーミング方式を使っています。"),
    "The template waveform has no bank id.": ("템플릿 파형에 뱅크 ID가 없습니다.", "テンプレートの波形にバンクIDがありません。"),
    "The rebuilt cue sheet does not name its cue.": ("다시 만든 큐 시트에 큐 이름이 없습니다.", "作り直したキューシートにキュー名がありません。"),
    "The decode quality floor must be a number of decibels.": (
        "디코딩 품질 하한은 데시벨 숫자여야 합니다.", "デコード品質の下限はデシベルの数値にしてください。"),
    "The app's HCA decoder is missing, so the new audio cannot be checked.": (
        "앱의 HCA 디코더가 없어 새 음원을 확인할 수 없습니다.", "アプリのHCAデコーダーがないため、新しい音源を確認できません。"),
    "The new audio does not decode to the input's length and channels.": (
        "새 음원을 디코딩하면 길이나 채널 수가 입력과 다릅니다.", "新しい音源をデコードすると、長さまたはチャンネル数が入力と一致しません。"),
    "The decoded audio differs too much from the input.": ("디코딩한 음원이 입력과 너무 다릅니다.", "デコードした音源が入力と違いすぎます。"),
    "The cue sheet has an invalid string offset.": ("큐 시트의 문자열 위치가 잘못되었습니다.", "キューシートの文字列の位置が正しくありません。"),
    "The cue sheet has an unterminated string.": ("큐 시트에 끝나지 않은 문자열이 있습니다.", "キューシートに終端のない文字列があります。"),
    "The cue sheet has an unsupported column type.": ("큐 시트에 지원하지 않는 열 형식이 있습니다.", "キューシートに対応していない列の型があります。"),
    "The cue sheet has a truncated column.": ("큐 시트의 열이 잘렸습니다.", "キューシートの列が途中で切れています。"),
    "The cue sheet has a truncated column declaration.": ("큐 시트의 열 선언이 잘렸습니다.", "キューシートの列の宣言が途中で切れています。"),
    "The cue sheet has an unsupported column declaration.": (
        "큐 시트에 지원하지 않는 열 선언이 있습니다.", "キューシートに対応していない列の宣言があります。"),
    "The audio bank (AWB) cannot be read.": ("오디오 뱅크(AWB)를 읽을 수 없습니다.", "オーディオバンク（AWB）を読み込めません。"),
    "The beat table needs at least one tempo.": ("비트 테이블에는 템포가 하나 이상 필요합니다.", "ビートテーブルにはテンポが1つ以上必要です。"),
    "Each tempo needs a BPM and a start sample.": ("템포마다 BPM과 시작 샘플이 필요합니다.", "テンポごとにBPMと開始サンプルが必要です。"),
    "The first beat must be a time inside the song.": ("첫 박은 곡 안의 시간이어야 합니다.", "最初の拍は曲の範囲内の時間にしてください。"),
    "The BPM must be a number between 0 and 1000.": ("BPM은 0과 1000 사이의 숫자여야 합니다.", "BPMは0から1000の間の数値にしてください。"),
    "The beats must start inside the song, in order.": ("박은 곡 안에서 순서대로 시작해야 합니다.", "拍は曲の範囲内で順番に始まる必要があります。"),
    "The template cue sheet cannot be read.": ("템플릿 큐 시트를 읽을 수 없습니다.", "テンプレートのキューシートを読み込めません。"),
    "The template cue sheet does not have the stock music layout.": (
        "템플릿 큐 시트가 게임 원래 음악의 구조가 아닙니다.", "テンプレートのキューシートがゲーム本来の楽曲の構造ではありません。"),
    "The template stream-only cue has an unexpected memory bank.": (
        "스트리밍 전용 템플릿 큐에 예상하지 않은 메모리 뱅크가 있습니다.",
        "ストリーミング専用のテンプレートのキューに想定外のメモリーバンクがあります。"),
    "The template's memory and stream banks use different keys.": (
        "템플릿의 메모리 뱅크와 스트림 뱅크가 서로 다른 키를 씁니다.",
        "テンプレートのメモリーバンクとストリームバンクが異なるキーを使っています。"),
    "The template cue sheet has no memory bank column.": (
        "템플릿 큐 시트에 메모리 뱅크 열이 없습니다.", "テンプレートのキューシートにメモリーバンクの列がありません。"),
    "The template cue sheet has no stream bank hash.": (
        "템플릿 큐 시트에 스트림 뱅크 해시가 없습니다.", "テンプレートのキューシートにストリームバンクのハッシュがありません。"),
    "The template cue sheet has no beat table.": ("템플릿 큐 시트에 비트 테이블이 없습니다.", "テンプレートのキューシートにビートテーブルがありません。"),
    "The new audio was not decoded by the app's HCA decoder.": (
        "새 음원을 앱의 HCA 디코더로 디코딩하지 않았습니다.", "新しい音源はアプリのHCAデコーダーでデコードされませんでした。"),
    "The cue sheet has an undecodable string.": ("큐 시트에 읽을 수 없는 문자열이 있습니다.", "キューシートに読み取れない文字列があります。"),
    "The cue sheet has an invalid data offset.": ("큐 시트의 데이터 위치가 잘못되었습니다.", "キューシートのデータの位置が正しくありません。"),
    "The template cue sheet has an unsupported stream bank header table.": (
        "템플릿 큐 시트의 스트림 뱅크 헤더 테이블을 지원하지 않습니다.",
        "テンプレートのキューシートのストリームバンクヘッダーテーブルに対応していません。"),
    "The new audio does not decode.": ("새 음원이 디코딩되지 않습니다.", "新しい音源をデコードできません。"),
}
for _source, (_korean, _japanese) in _MV_REGISTER_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# Apply to game (mv-studio-apply.js, core/mv_studio_apply.py, Elichika's mv_studio_stock): the panel,
# the job stages and every message the plan, the jobs and the stock MV store can show. Strings the
# registration panel already has (server notes, download, backup, confirm buttons) are not repeated.
_MV_APPLY_TRANSLATIONS = {
    # Panel
    "Apply to game": ("게임에 적용", "ゲームに適用"),
    "Apply only the edits": ("수정 사항만 적용", "修正だけを適用"),
    "Apply all": ("전체 적용", "全体を適用"),
    "Restore the original MV": ("원래대로 되돌리기", "元のMVに戻す"),
    "Checking the game's timeline…": ("게임의 타임라인 확인 중…", "ゲームのタイムラインを確認中…"),
    "Open this panel to check the game's timeline.": (
        "이 패널을 열면 게임의 타임라인을 확인합니다.", "このパネルを開くとゲームのタイムラインを確認します。"),
    "Load the MV from the game to apply it.": (
        "게임에 적용하려면 게임에서 MV를 불러오세요.", "ゲームに適用するには、ゲームからMVを読み込んでください。"),
    "Register as a new MV-only song…": ("새 MV 전용 곡으로 등록…", "新しいMV専用曲として登録…"),
    "MV-only song: {title} ({id})": ("MV 전용 곡: {title} ({id})", "MV専用曲: {title}（{id}）"),
    "Game MV: {title} ({id})": ("게임 MV: {title} ({id})", "ゲームのMV: {title}（{id}）"),
    "In the game: MV Studio version {revision} ({date})": (
        "게임: MV Studio 버전 {revision} ({date})", "ゲーム: MV Studio版 {revision}（{date}）"),
    "In the game: the original MV": ("게임: 원본 MV", "ゲーム: 元のMV"),
    "Loaded from: the registered song": ("불러온 것: 등록된 곡", "読み込み元: 登録済みの曲"),
    "Loaded from: MV Studio version {revision}": ("불러온 것: MV Studio 버전 {revision}", "読み込み元: MV Studio版 {revision}"),
    "Loaded from: an MV Studio version": ("불러온 것: MV Studio 버전", "読み込み元: MV Studio版"),
    "Loaded from: the original MV": ("불러온 것: 원본 MV", "読み込み元: 元のMV"),
    "This MV also plays in the 3D live of {count} songs: {titles}": (
        "이 MV는 곡 {count}개의 3D 라이브에서도 재생됩니다: {titles}", "このMVは{count}曲の3Dライブでも再生されます: {titles}"),
    "The song's 3D live plays this MV too.": (
        "이 곡의 3D 라이브에서도 이 MV가 재생됩니다.", "この曲の3DライブでもこのMVが再生されます。"),
    "Only the {region} game changes. The other region keeps its MV.": (
        "{region} 게임만 바뀝니다. 다른 지역은 지금의 MV를 그대로 둡니다.", "{region}のゲームだけが変わります。ほかの地域は今のMVのままです。"),
    "The game's MV changed after this project was loaded. Apply only the edits keeps those changes; Apply all replaces them.": (
        "이 프로젝트를 불러온 뒤 게임의 MV가 바뀌었습니다. '수정 사항만 적용'은 그 변경을 유지하고, '전체 적용'은 덮어씁니다.",
        "このプロジェクトを読み込んだ後にゲームのMVが変わりました。「修正だけを適用」はその変更を残し、「全体を適用」は置き換えます。"),
    "Edits: none since the last apply": ("수정 사항: 마지막 적용 이후 없음", "修正: 前回の適用以降なし"),
    "Edits: none since loading": ("수정 사항: 불러온 뒤 없음", "修正: 読み込み以降なし"),
    "Edits since the last apply: {clips} clips (camera {camera} · values {values} · timing {timing})": (
        "마지막 적용 이후 수정: 클립 {clips}개 (카메라 {camera} · 값 {values} · 타이밍 {timing})",
        "前回の適用以降の修正: クリップ{clips}個（カメラ{camera}・値{values}・タイミング{timing}）"),
    "Edits since loading: {clips} clips (camera {camera} · values {values} · timing {timing})": (
        "불러온 뒤 수정: 클립 {clips}개 (카메라 {camera} · 값 {values} · 타이밍 {timing})",
        "読み込み以降の修正: クリップ{clips}個（カメラ{camera}・値{values}・タイミング{timing}）"),
    "Apply all: the game already plays this project.": (
        "전체 적용: 게임이 이미 이 프로젝트대로 재생합니다.", "全体を適用: ゲームはすでにこのプロジェクトのとおり再生しています。"),
    "Apply all: the game plays the original MV again.": (
        "전체 적용: 게임이 원본 MV를 다시 재생합니다.", "全体を適用: ゲームは元のMVを再び再生します。"),
    "Apply all: {clips} clips differ from the original MV": (
        "전체 적용: 원본 MV와 다른 클립 {clips}개", "全体を適用: 元のMVと異なるクリップ{clips}個"),
    "Changed differently in the game ({count})": ("게임에서 다르게 바뀐 항목 ({count})", "ゲームで別の内容に変わった項目（{count}）"),
    "{where}: loaded {loaded} → project {project}, game {game}": (
        "{where}: 불러온 값 {loaded} → 프로젝트 {project}, 게임 {game}", "{where}: 読み込み時 {loaded} → プロジェクト {project}、ゲーム {game}"),
    "{where}: last applied {loaded} → project {project}, game {game}": (
        "{where}: 마지막 적용 값 {loaded} → 프로젝트 {project}, 게임 {game}",
        "{where}: 前回の適用時 {loaded} → プロジェクト {project}、ゲーム {game}"),
    "These edits are not in {platform} yet.": (
        "이 수정 사항은 아직 {platform}에 적용되지 않았습니다.", "この修正はまだ{platform}に適用されていません。"),
    "Nothing was overwritten. Use Apply all to replace the game's version with this project, or load the MV from the game again.": (
        "아무것도 덮어쓰지 않았습니다. 게임의 버전을 이 프로젝트로 바꾸려면 '전체 적용'을 쓰거나, 게임에서 MV를 다시 불러오세요.",
        "何も上書きしていません。ゲームの版をこのプロジェクトで置き換えるには「全体を適用」を使うか、ゲームからMVを読み込み直してください。"),
    "The game server stops for a moment while the game catalog is written.": (
        "게임 목록에 쓰는 동안 게임 서버가 잠시 멈춥니다.", "ゲームの一覧に書き込む間、ゲームサーバーが少し止まります。"),
    "Restart the game server after applying.": ("적용한 뒤 게임 서버를 다시 시작하세요.", "適用した後にゲームサーバーを再起動してください。"),
    "Restore the original MV? The MV Studio version {revision} stays in a backup.": (
        "원본 MV로 되돌릴까요? 지금의 MV Studio 버전({revision})은 백업에 남습니다.", "元のMVに戻しますか？ MV Studio版 {revision}はバックアップに残ります。"),
    "Apply all replaces the game's MV Studio version {revision} with this project. A backup is made first. Continue?": (
        "'전체 적용'은 게임의 MV Studio 버전({revision})을 이 프로젝트로 바꿉니다. 먼저 백업합니다. 계속할까요?",
        "「全体を適用」はゲームのMV Studio版 {revision}をこのプロジェクトで置き換えます。先にバックアップします。続けますか？"),
    "Apply all writes this whole project over the game's original MV. A backup is made first. Continue?": (
        "'전체 적용'은 이 프로젝트 전체를 게임의 원본 MV 위에 씁니다. 먼저 백업합니다. 계속할까요?",
        "「全体を適用」はこのプロジェクト全体をゲームの元のMVに書き込みます。先にバックアップします。続けますか？"),
    "Android and iOS keep the MV they play now. Continue?": (
        "Android와 iOS는 지금 재생하는 MV를 그대로 둡니다. 계속할까요?", "AndroidとiOSは今再生しているMVのままです。続けますか？"),
    "iOS keeps the MV it plays now. Continue?": ("iOS는 지금 재생하는 MV를 그대로 둡니다. 계속할까요?", "iOSは今再生しているMVのままです。続けますか？"),
    "Android keeps the MV it plays now. Continue?": (
        "Android는 지금 재생하는 MV를 그대로 둡니다. 계속할까요?", "Androidは今再生しているMVのままです。続けますか？"),
    "Restored the original MV: {title}.": ("원본 MV로 되돌렸습니다: {title}.", "元のMVに戻しました: {title}。"),
    "Applied to the game: {title}.": ("게임에 적용했습니다: {title}.", "ゲームに適用しました: {title}。"),
    "Applying to the game was cancelled.": ("게임에 적용하는 작업을 취소했습니다.", "ゲームへの適用を取り消しました。"),
    # Job stages
    "Checking the game's timeline": ("게임의 타임라인 확인", "ゲームのタイムラインを確認"),
    "Applying the edits to the Android timeline": ("Android 타임라인에 수정 사항 적용 중", "Androidのタイムラインに修正を適用中"),
    "Applying the edits to the iOS timeline": ("iOS 타임라인에 수정 사항 적용 중", "iOSのタイムラインに修正を適用中"),
    "Checking the timelines against the original MV": ("원본 MV와 타임라인 대조", "元のMVとタイムラインを照合"),
    "Restoring the original MV": ("원본 MV로 되돌리는 중", "元のMVに戻している途中"),
    # Plan and job messages (core/mv_studio_apply.py, mv_studio_timeline.merge_changes)
    "This Elichika version cannot change stock MVs. Update the Elichika server app.": (
        "이 Elichika 버전은 게임 기본 MV를 바꿀 수 없습니다. Elichika 서버 앱을 업데이트하세요.",
        "このバージョンのElichikaではゲーム標準のMVを変更できません。Elichikaサーバーアプリを更新してください。"),
    "The timeline this project was loaded from is unavailable. Load the MV from the game again.": (
        "이 프로젝트를 불러온 타임라인을 찾을 수 없습니다. 게임에서 MV를 다시 불러오세요.",
        "このプロジェクトの読み込み元のタイムラインが見つかりません。ゲームからMVを読み込み直してください。"),
    "The MV-only song this project was loaded from was removed. Register the project as a new song.": (
        "이 프로젝트를 불러온 MV 전용 곡이 삭제되었습니다. 프로젝트를 새 곡으로 등록하세요.",
        "このプロジェクトの読み込み元のMV専用曲は削除されました。プロジェクトを新しい曲として登録してください。"),
    "The MV in the game has a different track layout. Use Apply all.": (
        "게임의 MV는 트랙 구성이 다릅니다. '전체 적용'을 쓰세요.", "ゲームのMVはトラック構成が異なります。「全体を適用」を使ってください。"),
    "Some edits were also changed differently in the game since this project was loaded. Use Apply all, or load the MV from the game again.": (
        "일부 수정 항목이 이 프로젝트를 불러온 뒤 게임에서 다르게 바뀌었습니다. '전체 적용'을 쓰거나, 게임에서 MV를 다시 불러오세요.",
        "一部の修正項目は、このプロジェクトを読み込んだ後にゲームで別の内容に変わりました。「全体を適用」を使うか、ゲームからMVを読み込み直してください。"),
    "The game's timeline changed after the check. Check it again, then apply.": (
        "확인한 뒤 게임의 타임라인이 바뀌었습니다. 다시 확인한 다음 적용하세요.",
        "確認の後にゲームのタイムラインが変わりました。確認し直してから適用してください。"),
    "The project changed after the last check. Check it again, then apply.": (
        "마지막 확인 뒤 프로젝트가 바뀌었습니다. 다시 확인한 다음 적용하세요.",
        "前回の確認の後にプロジェクトが変わりました。確認し直してから適用してください。"),
    "Choose Apply all or Apply only the edits.": (
        "'전체 적용' 또는 '수정 사항만 적용'을 고르세요.", "「全体を適用」か「修正だけを適用」を選んでください。"),
    "The apply request is invalid.": ("적용 요청이 올바르지 않습니다.", "適用のリクエストが正しくありません。"),
    "There are no edits since this project was loaded.": (
        "이 프로젝트를 불러온 뒤 수정한 것이 없습니다.", "このプロジェクトを読み込んだ後の修正はありません。"),
    "The MV already plays its original timeline.": ("이 MV는 이미 원본 타임라인을 재생합니다.", "このMVはすでに元のタイムラインを再生しています。"),
    "The Android timeline the game plays now is not available. Allow the download, or apply to iOS only.": (
        "게임이 지금 재생하는 Android 타임라인을 찾을 수 없습니다. 다운로드를 허용하거나 iOS에만 적용하세요.",
        "ゲームが今再生しているAndroidのタイムラインが見つかりません。ダウンロードを許可するか、iOSだけに適用してください。"),
    "The iOS timeline the game plays now is not available. Allow the download, or apply to Android only.": (
        "게임이 지금 재생하는 iOS 타임라인을 찾을 수 없습니다. 다운로드를 허용하거나 Android에만 적용하세요.",
        "ゲームが今再生しているiOSのタイムラインが見つかりません。ダウンロードを許可するか、Androidだけに適用してください。"),
    "The Android and iOS timelines the game plays now differ. Each platform keeps its own changes.": (
        "게임이 지금 재생하는 Android와 iOS 타임라인이 서로 다릅니다. 플랫폼마다 각자의 변경을 유지합니다.",
        "ゲームが今再生しているAndroidとiOSのタイムラインが異なります。プラットフォームごとにそれぞれの変更を残します。"),
    # Elichika's stock MV store (mv_studio_stock.MESSAGES)
    "Choose a 3D MV of this region.": ("이 지역의 3D MV를 고르세요.", "この地域の3D MVを選んでください。"),
    "The selected MV has no 3D timeline in this region.": (
        "고른 MV는 이 지역에 3D 타임라인이 없습니다.", "選んだMVにはこの地域の3Dタイムラインがありません。"),
    "This MV belongs to an MV-only song. Update the song instead.": (
        "이 MV는 MV 전용 곡의 것입니다. 곡을 업데이트하세요.", "このMVはMV専用曲のものです。曲を更新してください。"),
    "Fingerprints must be short text values for android or ios.": (
        "지문 값은 android 또는 ios용 짧은 문자열이어야 합니다.", "フィンガープリントはandroidかios用の短い文字列にしてください。"),
}
for _source, (_korean, _japanese) in _MV_APPLY_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# Another MV slot, MV timeline packs and the MV timeline platform conversion
# (mv-studio-apply.js, core/mv_studio_apply.py, core/mv_studio_pack.py, core/mv_timeline_platform.py,
# tools/mv_timeline.py). Format names: "MV 타임라인 팩" / "MVタイムラインパック" (.sifasmv).
_MV_CROSS_SLOT_TRANSLATIONS = {
    # Panel: the slot
    "The MV this project was loaded from ({label})": ("지금 불러온 MV ({label})", "読み込んだMV（{label}）"),
    "Another 3D asset ID…": ("다른 3D 에셋 ID…", "別の3DアセットID…"),
    "Apply to MV slot": ("적용할 MV 슬롯", "適用するMVスロット"),
    "3D asset ID": ("3D 에셋 ID", "3DアセットID"),
    "Change the stage too": ("무대도 함께 바꾸기", "ステージも一緒に変える"),
    "The stage, stage effects, props, quality set and shader variant of 3D {asset} go with the timeline.": (
        "3D {asset}의 무대, 무대 효과, 소품, 품질 세트, 셰이더 변형이 타임라인과 함께 들어갑니다.",
        "3D {asset}のステージ、ステージ効果、小道具、品質セット、シェーダーバリアントがタイムラインと一緒に入ります。"),
    "This region only ({region})": ("이 지역만 ({region})", "この地域のみ（{region}）"),
    "Both GL and JP": ("GL과 JP 모두", "GLとJPの両方"),
    "Regions": ("지역", "地域"),
    "Target: {label}": ("적용 대상: {label}", "適用先：{label}"),
    "From: {title} · 3D {asset}": ("가져오는 MV: {title} · 3D {asset}", "元のMV：{title} · 3D {asset}"),
    "Another slot takes this project's whole timeline. Apply only the edits works only on the slot the project was loaded from.": (
        "다른 슬롯에는 이 프로젝트의 타임라인 전체가 들어갑니다. '수정 사항만 적용'은 프로젝트를 불러온 슬롯에서만 쓸 수 있습니다.",
        "別のスロットにはこのプロジェクトのタイムライン全体が入ります。「修正だけを適用」はプロジェクトを読み込んだスロットでのみ使えます。"),
    "Lives that play 3D {asset} ({count}): {titles}. Their rhythm-game 3D lives change too.": (
        "3D {asset}을(를) 쓰는 라이브 ({count}): {titles}. 리듬 게임의 3D 라이브도 함께 바뀝니다.",
        "3D {asset}を使うライブ（{count}）：{titles}。リズムゲームの3Dライブも一緒に変わります。"),
    "The GL and JP games both change.": ("GL과 JP 게임이 모두 바뀝니다.", "GLとJPの両方のゲームが変わります。"),
    "The source MV's stage goes with the timeline, so its stage tracks find their objects.": (
        "원래 MV의 무대가 타임라인과 함께 들어가므로 무대 트랙이 대상 오브젝트를 찾을 수 있습니다.",
        "元のMVのステージがタイムラインと一緒に入るので、ステージのトラックは対象のオブジェクトを見つけられます。"),
    "Without its stage, {count} stage tracks of this timeline address objects of the source stage that the target stage may not have. Effects can be missing, or the MV may fail to load in the game.": (
        "무대를 함께 바꾸지 않으면 이 타임라인의 무대 트랙 {count}개가 원래 무대의 오브젝트를 가리키는데, 대상 무대에는 그 오브젝트가 없을 수 있습니다. 효과가 빠지거나 게임에서 MV를 불러오지 못할 수 있습니다.",
        "ステージを一緒に変えないと、このタイムラインのステージトラック{count}個が元のステージのオブジェクトを指しますが、適用先のステージにはそのオブジェクトがないことがあります。効果が欠けたり、ゲームでMVを読み込めなかったりすることがあります。"),
    "No {platform} timeline yet: it is converted from {from} when you apply.": (
        "{platform} 타임라인이 아직 없습니다: 적용할 때 {from}에서 변환합니다.",
        "{platform}のタイムラインはまだありません。適用するときに{from}から変換します。"),
    "Apply to 3D {asset}": ("3D {asset}에 적용", "3D {asset}に適用"),
    "Restore the original MV of 3D {asset}": ("3D {asset} 원래대로 되돌리기", "3D {asset}を元のMVに戻す"),
    "Restore the original MV of 3D {asset}? Its timeline and stage go back to the game's own.": (
        "3D {asset}을(를) 원래 MV로 되돌릴까요? 타임라인과 무대가 게임 원래의 것으로 돌아갑니다.",
        "3D {asset}を元のMVに戻しますか？タイムラインとステージがゲーム本来のものに戻ります。"),
    "Put this project's whole timeline and its stage into 3D {asset}? A backup is made first.": (
        "이 프로젝트의 타임라인 전체와 무대를 3D {asset}에 넣을까요? 먼저 백업을 만듭니다.",
        "このプロジェクトのタイムライン全体とステージを3D {asset}に入れますか？先にバックアップを作ります。"),
    "Put this project's whole timeline into 3D {asset}? Its stage stays. A backup is made first.": (
        "이 프로젝트의 타임라인 전체를 3D {asset}에 넣을까요? 무대는 그대로 둡니다. 먼저 백업을 만듭니다.",
        "このプロジェクトのタイムライン全体を3D {asset}に入れますか？ステージはそのままです。先にバックアップを作ります。"),
    "The game has no {platform} original of 3D {asset}, so no {platform} timeline can be made.": (
        "게임에 3D {asset}의 {platform} 원본이 없어서 {platform} 타임라인을 만들 수 없습니다.",
        "ゲームに3D {asset}の{platform}の元データがないため、{platform}のタイムラインを作れません。"),
    "No {platform} timeline is ready for this slot. It can be converted from {from} with the {platform} original of 3D {asset} (about {size} MB to download).": (
        "이 슬롯에 넣을 {platform} 타임라인이 없습니다. 3D {asset}의 {platform} 원본(약 {size} MB 다운로드)으로 {from}에서 변환할 수 있습니다.",
        "このスロットに入れる{platform}のタイムラインがありません。3D {asset}の{platform}の元データ（約{size} MBのダウンロード）を使って{from}から変換できます。"),
    "The stage changes for both platforms.": ("무대는 두 플랫폼 모두 바뀝니다.", "ステージは両方のプラットフォームで変わります。"),
    "Convert from {from}": ("{from}에서 변환", "{from}から変換"),
    "Apply to {from} only": ("{from}에만 적용", "{from}だけに適用"),
    # Panel: MV timeline packs
    "MV timeline pack": ("MV 타임라인 팩", "MVタイムラインパック"),
    "Opened from the MV timeline pack “{name}”": ("MV 타임라인 팩 “{name}”에서 열었습니다",
                                                            "MVタイムラインパック「{name}」から開きました"),
    "Export MV timeline pack…": ("MV 타임라인 팩 내보내기…", "MVタイムラインパックを書き出す…"),
    "Open MV timeline pack…": ("MV 타임라인 팩 열기…", "MVタイムラインパックを開く…"),
    "Open MV timeline pack": ("MV 타임라인 팩 열기", "MVタイムラインパックを開く"),
    "Pack name": ("팩 이름", "パック名"),
    "Note": ("메모", "メモ"),
    "Target slot: 3D {asset}, with the stage.": ("적용 슬롯: 3D {asset}, 무대 포함.", "適用スロット：3D {asset}、ステージ込み。"),
    "Target slot: 3D {asset}, without the stage.": ("적용 슬롯: 3D {asset}, 무대 제외.", "適用スロット：3D {asset}、ステージなし。"),
    "Target slot: 3D {asset} (the loaded MV).": ("적용 슬롯: 3D {asset} (지금 불러온 MV).", "適用スロット：3D {asset}（読み込んだMV）。"),
    "Export": ("내보내기", "書き出す"),
    "Writing the MV timeline pack…": ("MV 타임라인 팩을 쓰는 중…", "MVタイムラインパックを書き出し中…"),
    "Not in the pack: {platforms} (its original is not available).": (
        "팩에 넣지 못함: {platforms} (원본을 구할 수 없음).", "パックに入っていません：{platforms}（元データがありません）。"),
    # core/mv_studio_apply.py
    "This Elichika version cannot put an MV into another slot. Update the Elichika server app to apply it to another 3D MV.": (
        "이 Elichika 버전은 MV를 다른 슬롯에 넣을 수 없습니다. 다른 3D MV에 적용하려면 Elichika 서버 앱을 업데이트하세요.",
        "このElichikaのバージョンはMVを別のスロットに入れられません。別の3D MVに適用するにはElichikaサーバーアプリを更新してください。"),
    "Choose the MV slot to apply to.": ("적용할 MV 슬롯을 선택하세요.", "適用するMVスロットを選んでください。"),
    "3D MV {asset} is not in the {region} game.": ("3D MV {asset}이(가) {region} 게임에 없습니다.", "3D MV {asset}は{region}のゲームにありません。"),
    "3D MV {asset} belongs to an MV-only song. Choose a stock 3D MV.": (
        "3D MV {asset}은(는) MV 전용 곡의 것입니다. 게임 원래의 3D MV를 선택하세요.",
        "3D MV {asset}はMV専用曲のものです。ゲーム本来の3D MVを選んでください。"),
    "3D MV {asset} this project was loaded from is not in the {region} game.": (
        "이 프로젝트를 불러온 3D MV {asset}이(가) {region} 게임에 없습니다.",
        "このプロジェクトを読み込んだ3D MV {asset}は{region}のゲームにありません。"),
    "A project opened from an MV-only song can only update that song. Load a stock MV to apply it to another slot.": (
        "MV 전용 곡에서 연 프로젝트는 그 곡만 업데이트할 수 있습니다. 다른 슬롯에 적용하려면 게임 원래의 MV를 불러오세요.",
        "MV専用曲から開いたプロジェクトはその曲だけを更新できます。別のスロットに適用するにはゲーム本来のMVを読み込んでください。"),
    "Only Apply all can put a timeline into another MV slot.": (
        "다른 MV 슬롯에는 '전체 적용'으로만 타임라인을 넣을 수 있습니다.",
        "別のMVスロットには「全体を適用」でのみタイムラインを入れられます。"),
    "No Android timeline can be made for the chosen slot. Apply to iOS only, or cancel.": (
        "선택한 슬롯에 넣을 Android 타임라인을 만들 수 없습니다. iOS에만 적용하거나 취소하세요.",
        "選んだスロットに入れるAndroidのタイムラインを作れません。iOSだけに適用するか、キャンセルしてください。"),
    "No iOS timeline can be made for the chosen slot. Apply to Android only, or cancel.": (
        "선택한 슬롯에 넣을 iOS 타임라인을 만들 수 없습니다. Android에만 적용하거나 취소하세요.",
        "選んだスロットに入れるiOSのタイムラインを作れません。Androidだけに適用するか、キャンセルしてください。"),
    "Only the GL game was changed. The JP game could not be changed; see the job log.": (
        "GL 게임만 바뀌었습니다. JP 게임은 바꾸지 못했습니다. 작업 로그를 확인하세요.",
        "GLのゲームだけが変わりました。JPのゲームは変えられませんでした。ジョブのログを確認してください。"),
    "Only the JP game was changed. The GL game could not be changed; see the job log.": (
        "JP 게임만 바뀌었습니다. GL 게임은 바꾸지 못했습니다. 작업 로그를 확인하세요.",
        "JPのゲームだけが変わりました。GLのゲームは変えられませんでした。ジョブのログを確認してください。"),
    # core/mv_studio_pack.py
    "This Elichika version cannot read or write MV timeline packs. Update the Elichika server app.": (
        "이 Elichika 버전은 MV 타임라인 팩을 읽거나 쓸 수 없습니다. Elichika 서버 앱을 업데이트하세요.",
        "このElichikaのバージョンはMVタイムラインパックを読み書きできません。Elichikaサーバーアプリを更新してください。"),
    "This file is not an MV timeline pack.": ("이 파일은 MV 타임라인 팩이 아닙니다.", "このファイルはMVタイムラインパックではありません。"),
    "Enter a pack name between 1 and 80 characters.": ("팩 이름을 1~80자로 입력하세요.", "パック名を1〜80文字で入力してください。"),
    "Enter a note of at most 500 characters.": ("메모는 500자 이하로 입력하세요.", "メモは500文字以内で入力してください。"),
    "The pack has no timeline this MV Studio can open.": ("이 팩에는 MV 스튜디오가 열 수 있는 타임라인이 없습니다.",
                                                         "このパックにはMVスタジオで開けるタイムラインがありません。"),
    "The opened pack is no longer available. Open it again.": ("열었던 팩을 더 이상 쓸 수 없습니다. 다시 여세요.",
                                                              "開いたパックはもう使えません。もう一度開いてください。"),
    "The game has no song that plays this pack's 3D MV.": ("이 팩의 3D MV를 재생하는 곡이 게임에 없습니다.",
                                                          "このパックの3D MVを再生する曲がゲームにありません。"),
    "The MV timeline pack request is invalid.": ("MV 타임라인 팩 요청이 올바르지 않습니다.", "MVタイムラインパックのリクエストが正しくありません。"),
    # core/mv_timeline_platform.py and the tool
    "MV timeline platform conversion": ("MV 타임라인 플랫폼 변환", "MVタイムラインのプラットフォーム変換"),
    "Convert an MV timeline (.unity) or an MV timeline pack (.sifasmv) for Android (APK) or iOS using the same 3D MV's original timeline from the output platform.": (
        "변환할 플랫폼에 있는 같은 3D MV의 원본 타임라인을 사용해 MV 타임라인(.unity)이나 MV 타임라인 팩(.sifasmv)을 Android (APK) 또는 iOS용으로 변환합니다.",
        "変換先のプラットフォームにある同じ3D MVの元のタイムラインを使って、MVタイムライン（.unity）またはMVタイムラインパック（.sifasmv）をAndroid (APK) またはiOS用に変換します。"),
    "MV timeline (.unity) or MV timeline pack (.sifasmv)": ("MV 타임라인(.unity) 또는 MV 타임라인 팩(.sifasmv)",
                                                            "MVタイムライン（.unity）またはMVタイムラインパック（.sifasmv）"),
    "A pack names its own region and 3D MV; the platform it lacks is added.": (
        "팩에는 지역과 3D MV가 적혀 있어서, 팩에 없는 플랫폼이 추가됩니다.",
        "パックには地域と3D MVが書かれているので、パックにないプラットフォームが追加されます。"),
    "3D asset ID of the timeline's MV": ("타임라인의 3D 에셋 ID", "タイムラインの3DアセットID"),
    "For a .unity timeline: the 3D MV it was made from (MV Studio shows it, e.g. 3D 1012003).": (
        ".unity 타임라인일 때: 그 타임라인을 만든 3D MV (MV 스튜디오에 표시됨, 예: 3D 1012003).",
        ".unityのタイムラインの場合：作成元の3D MV（MVスタジオに表示されます。例：3D 1012003）。"),
    "Download the original timeline for the output platform if missing": (
        "변환할 플랫폼의 원본 타임라인이 없으면 다운로드", "変換先のプラットフォームの元のタイムラインがなければダウンロード"),
    "Choose Android or iOS.": ("Android 또는 iOS를 선택하세요.", "AndroidかiOSを選んでください。"),
    "Enter the 3D asset ID of the MV this timeline belongs to.": ("이 타임라인이 속한 MV의 3D 에셋 ID를 입력하세요.",
                                                                 "このタイムラインのMVの3DアセットIDを入力してください。"),
    "The timeline is already for the output platform.": ("이미 변환할 플랫폼용 타임라인입니다.", "すでに変換先のプラットフォーム用のタイムラインです。"),
    "The timeline is not for the chosen source platform.": ("선택한 원래 플랫폼용 타임라인이 아닙니다.", "選んだ変換元のプラットフォーム用のタイムラインではありません。"),
    "This file is not a native live timeline.": ("이 파일은 게임의 라이브 타임라인이 아닙니다.", "このファイルはゲームのライブタイムラインではありません。"),
    "This 3D MV is not in the game catalog of this region.": ("이 3D MV는 이 지역의 게임 카탈로그에 없습니다.", "この3D MVはこの地域のゲームカタログにありません。"),
    "The game catalog has no original timeline of this 3D MV for the output platform.": (
        "게임 카탈로그에 이 3D MV의 변환할 플랫폼용 원본 타임라인이 없습니다.",
        "ゲームカタログにこの3D MVの変換先プラットフォーム用の元のタイムラインがありません。"),
    "The original timeline of this 3D MV for the output platform is not available locally. Allow the download.": (
        "이 3D MV의 변환할 플랫폼용 원본 타임라인이 로컬에 없습니다. 다운로드를 허용하세요.",
        "この3D MVの変換先プラットフォーム用の元のタイムラインがローカルにありません。ダウンロードを許可してください。"),
    "The timeline does not belong to this 3D MV:": ("이 3D MV의 타임라인이 아닙니다:", "この3D MVのタイムラインではありません："),
    "The converted timeline would differ from the source, so nothing was converted:": (
        "변환 결과가 원래 타임라인과 달라지므로 변환하지 않았습니다:", "変換結果が元のタイムラインと異なるため、変換しませんでした："),
    "The timeline holds data this server's MV Studio tools do not write: the pack was made by a newer MV Studio or changed elsewhere. Updating Elichika and its asset editing tools (modtools) lets this server check it.": (
        "타임라인에 이 서버의 MV Studio 도구가 쓰지 않는 데이터가 있습니다. 더 새로운 MV Studio로 만들었거나 다른 곳에서 바뀐 팩입니다. Elichika와 에셋 편집툴(modtools)을 업데이트하면 이 서버에서 확인할 수 있습니다.",
        "タイムラインに、このサーバーのMV Studioツールが書き込まないデータがあります。より新しいMV Studioで作られたか、ほかの場所で変更されたパックです。Elichikaとアセット編集ツール（modtools）を更新すると、このサーバーで確認できます。"),
    "The pack was made by a newer MV Studio: its timeline holds data this server's MV Studio tools do not write. Updating Elichika and its asset editing tools (modtools) lets this server check it.": (
        "더 새로운 MV Studio로 만든 팩입니다. 타임라인에 이 서버의 MV Studio 도구가 쓰지 않는 데이터가 있습니다. Elichika와 에셋 편집툴(modtools)을 업데이트하면 이 서버에서 확인할 수 있습니다.",
        "より新しいMV Studioで作られたパックです。タイムラインに、このサーバーのMV Studioツールが書き込まないデータがあります。Elichikaとアセット編集ツール（modtools）を更新すると、このサーバーで確認できます。"),
    "The timeline's values could not be checked: the check ran out of time or memory, or the original timeline was not available.": (
        "타임라인 값을 확인하지 못했습니다. 확인 시간이나 메모리가 부족했거나 원래 타임라인을 쓸 수 없었습니다.",
        "タイムラインの値を確認できませんでした。確認の時間かメモリが足りなかったか、元のタイムラインを使えませんでした。"),
    "Choose the conversion direction.": ("변환 방향을 선택하세요.", "変換の方向を選んでください。"),
    "Choose a native MV timeline (.unity) or an MV timeline pack (.sifasmv).": (
        "MV 타임라인(.unity)이나 MV 타임라인 팩(.sifasmv)을 선택하세요.", "MVタイムライン（.unity）かMVタイムラインパック（.sifasmv）を選んでください。"),
    "Choose the output folder.": ("출력 폴더를 선택하세요.", "出力フォルダを選んでください。"),
    "The pack already has Android and iOS timelines.": ("이 팩에는 이미 Android와 iOS 타임라인이 모두 있습니다.",
                                                       "このパックにはすでにAndroidとiOSの両方のタイムラインがあります。"),
    "Choose whether to download the missing original timeline.": ("없는 원본 타임라인을 다운로드할지 선택하세요.",
                                                                 "ない元のタイムラインをダウンロードするか選んでください。"),
    "Left out, {platform} plays the original timeline of 3D {asset}.": (
        "제외하면 {platform}은(는) 3D {asset}의 원본 타임라인을 재생합니다.",
        "外すと、{platform}は3D {asset}の元のタイムラインを再生します。"),
    "An old live timeline zip does not name the MV it was made from. Open it in MV Studio and export an MV timeline pack.": (
        "예전 라이브 타임라인 zip에는 어느 MV로 만들었는지 적혀 있지 않습니다. MV 스튜디오에서 열어 MV 타임라인 팩으로 내보내세요.",
        "古いライブタイムラインzipには作成元のMVが書かれていません。MVスタジオで開いてMVタイムラインパックとして書き出してください。"),
    # Elichika's mv_studio_stock (another slot, stage) and mv_timeline_pack messages, shown in this panel.
    "Choose the 3D MV of this region that the timeline was made from.": (
        "이 타임라인을 만든 이 지역의 3D MV를 선택하세요.", "このタイムラインの作成元となったこの地域の3D MVを選んでください。"),
    "The timeline's source MV belongs to an MV-only song. Choose a stock game MV.": (
        "타임라인을 만든 MV가 MV 전용 곡의 것입니다. 게임 원래의 MV를 선택하세요.",
        "タイムラインの作成元のMVはMV専用曲のものです。ゲーム本来のMVを選んでください。"),
    "The MV's source changes, so every platform needs its timeline again (or none, to play the source's original).": (
        "MV의 원본이 바뀌므로 모든 플랫폼에 타임라인을 다시 넣어야 합니다 (넣지 않으면 원본 MV의 타임라인을 재생합니다).",
        "MVの作成元が変わるので、すべてのプラットフォームにタイムラインを入れ直す必要があります（入れないと作成元の元のタイムラインを再生します）。"),
    "Choose the stage explicitly: a stage id, a stage effect and a quality set, with an optional prop skeleton and shader variant.": (
        "무대를 정확히 선택하세요: 무대 ID, 무대 효과, 품질 세트와 필요하면 소품 스켈레톤, 셰이더 변형.",
        "ステージを明示してください：ステージID、ステージ効果、品質セットと、必要なら小道具スケルトン、シェーダーバリアント。"),
    "The chosen stage, stage effect, prop skeleton or shader variant is not in this region's game catalogs.": (
        "선택한 무대, 무대 효과, 소품 스켈레톤 또는 셰이더 변형이 이 지역의 게임 카탈로그에 없습니다.",
        "選んだステージ、ステージ効果、小道具スケルトン、シェーダーバリアントのいずれかがこの地域のゲームカタログにありません。"),
    "The file is not a valid MV timeline pack.": ("올바른 MV 타임라인 팩 파일이 아닙니다.", "正しいMVタイムラインパックのファイルではありません。"),
    "The MV timeline pack is too large or has too many files.": ("MV 타임라인 팩이 너무 크거나 파일이 너무 많습니다.",
                                                                "MVタイムラインパックが大きすぎるか、ファイルが多すぎます。"),
    "The MV timeline pack contains a file name it may not use.": ("MV 타임라인 팩에 쓸 수 없는 파일 이름이 있습니다.",
                                                                 "MVタイムラインパックに使えないファイル名があります。"),
    "A timeline in the MV timeline pack is damaged or is not a UnityFS bundle.": (
        "MV 타임라인 팩의 타임라인이 손상되었거나 UnityFS 번들이 아닙니다.",
        "MVタイムラインパックのタイムラインが壊れているか、UnityFSバンドルではありません。"),
    "The MV timeline pack has no timeline.": ("MV 타임라인 팩에 타임라인이 없습니다.", "MVタイムラインパックにタイムラインがありません。"),
    "This MV timeline pack needs a newer Elichika.": ("이 MV 타임라인 팩은 더 새로운 Elichika가 필요합니다.",
                                                     "このMVタイムラインパックにはより新しいElichikaが必要です。"),
    "The live timeline zip has no readable livetimeline.txt or timeline file.": (
        "라이브 타임라인 zip에 읽을 수 있는 livetimeline.txt나 타임라인 파일이 없습니다.",
        "ライブタイムラインzipに読めるlivetimeline.txtかタイムラインファイルがありません。"),
    "The source MV's original timeline is not on this server. Install the asset editing tools (modtools) so Elichika can download it, then install again.": (
        "원본 MV의 원래 타임라인이 이 서버에 없습니다. Elichika가 내려받을 수 있도록 에셋 편집툴(modtools)을 설치한 뒤 다시 설치하세요.",
        "元MVの元のタイムラインがこのサーバーにありません。Elichikaがダウンロードできるようアセット編集ツール（modtools）をインストールしてから、もう一度インストールしてください。"),
    "The source MV's original timeline could not be downloaded. Check the connection, then install again.": (
        "원본 MV의 원래 타임라인을 내려받지 못했습니다. 연결을 확인한 뒤 다시 설치하세요.",
        "元MVの元のタイムラインをダウンロードできませんでした。接続を確認してから、もう一度インストールしてください。"),
    # Another region checks the timeline against its own original of the source MV
    "Checking the timeline for the other region needs the source MV's original timeline from that region's game. Allow the download, or apply to this region only.": (
        "다른 지역에서 타임라인을 확인하려면 그 지역 게임에 있는 원본 MV의 원래 타임라인이 필요합니다. 다운로드를 허용하거나 이 지역에만 적용하세요.",
        "もう一方の地域でタイムラインを確認するには、その地域のゲームにある元MVの元のタイムラインが必要です。ダウンロードを許可するか、この地域だけに適用してください。"),
    "Checking the timeline in {regions} needs the {platform} original of 3D {asset} from that game.": (
        "{regions}에서 타임라인을 확인하려면 그 게임에 있는 3D {asset}의 {platform} 원본이 필요합니다.",
        "{regions}でタイムラインを確認するには、そのゲームにある3D {asset}の{platform}の元データが必要です。"),
    "Checking the timeline in {regions} needs the {platform} original of 3D {asset} from that game (about {size} MB to download). Download it and apply?": (
        "{regions}에서 타임라인을 확인하려면 그 게임에 있는 3D {asset}의 {platform} 원본이 필요합니다 (약 {size} MB 다운로드). 내려받아 적용할까요?",
        "{regions}でタイムラインを確認するには、そのゲームにある3D {asset}の{platform}の元データが必要です（約{size} MBのダウンロード）。ダウンロードして適用しますか？"),
    # A slot that plays another slot's timeline
    "This slot plays the timeline of 3D {source}, put here from another slot. Load 3D {source} and apply it to this slot, or restore this slot first.": (
        "이 슬롯은 다른 슬롯에서 넣은 3D {source}의 타임라인을 재생합니다. 3D {source}를 불러와 이 슬롯에 적용하거나, 먼저 이 슬롯을 원래대로 되돌리세요.",
        "このスロットは別のスロットから入れた3D {source}のタイムラインを再生しています。3D {source}を読み込んでこのスロットに適用するか、先にこのスロットを元に戻してください。"),
    "This slot plays a timeline put here from another 3D MV. Load that MV and apply it to this slot, or restore this slot first.": (
        "이 슬롯은 다른 3D MV에서 넣은 타임라인을 재생합니다. 그 MV를 불러와 이 슬롯에 적용하거나, 먼저 이 슬롯을 원래대로 되돌리세요.",
        "このスロットは別の3D MVから入れたタイムラインを再生しています。そのMVを読み込んでこのスロットに適用するか、先にこのスロットを元に戻してください。"),
}
for _source, (_korean, _japanese) in _MV_CROSS_SLOT_TRANSLATIONS.items():
    _TABLES["ko"].setdefault(_source, _korean)
    _TABLES["ja"].setdefault(_source, _japanese)

# Texture authoring labels shared with the viewer save form.
_TABLES["ko"].update({
    "Open texture editor": "텍스쳐 편집기 열기",
    "Choose PNG image": "PNG 이미지 선택",
    "Choose texture project": "텍스쳐 작업 파일 선택",
    "Texture editor": "텍스쳐 편집기",
    "Costume colour": "의상 컬러",
    "Skin tone": "스킨톤",
    "Texture painting": "텍스쳐 페인팅",
    "Baked blush": "홍조 굽기",
    # Baked blush save summary (viewer_texture_tools / texture_block_splice).
    "The baked blush was saved as exact pixels (lossless RGBA32): every texel it does not change keeps its value.": "홍조를 정확한 픽셀(무손실 RGBA32)로 저장했습니다. 홍조가 바꾸지 않는 픽셀은 모두 원래 값을 유지합니다.",
    "The baked blush kept the game's ASTC compression: only the blocks it touches were compressed again, and every other block keeps its original bytes.": "홍조를 게임 압축 형식(ASTC) 그대로 저장했습니다. 홍조가 닿는 블록만 다시 압축했고, 나머지 블록은 원래 데이터 그대로입니다.",
    "This texture is also painted, and painted pixels are always saved exactly, so its ASTC compression was not kept.": "이 텍스쳐에는 그림판 편집도 있고, 그린 픽셀은 항상 정확하게 저장되므로 ASTC 압축을 유지하지 않았습니다.",
    "This texture is not ASTC-compressed, so there was no ASTC compression to keep.": "이 텍스쳐는 ASTC 압축이 아니어서 유지할 ASTC 압축이 없습니다.",
    "The ASTC encoder is unavailable.": "ASTC 인코더를 사용할 수 없습니다.",
    "The ASTC encoder could not be started.": "ASTC 인코더를 실행하지 못했습니다.",
    "The ASTC encoder could not re-encode the baked blocks.": "ASTC 인코더가 홍조 블록을 다시 압축하지 못했습니다.",
    "The ASTC encoder returned unexpected data.": "ASTC 인코더가 예상과 다른 데이터를 돌려주었습니다.",
    "Re-encoding the baked blocks took too long.": "홍조 블록을 다시 압축하는 데 시간이 너무 오래 걸렸습니다.",
    "Re-encoded blocks changed texels outside the baked area.": "다시 압축한 블록이 홍조 영역 밖의 픽셀까지 바꿨습니다.",
    "Re-encoding the baked blocks would change alpha.": "홍조 블록을 다시 압축하면 알파가 바뀝니다.",
    "The re-encoded blocks are not close enough to the bake.": "다시 압축한 블록이 구운 홍조와 너무 다릅니다.",
    "The original ASTC data is shorter than its mip chain.": "원본 ASTC 데이터가 밉맵 체인보다 짧습니다.",
    "Choose how to save the baked blush: exact pixels or the game's ASTC compression.": "홍조 저장 방식을 정확한 픽셀 또는 게임 압축 형식(ASTC) 유지 중에서 고르세요.",
    "The re-encoded ASTC blocks could not be decoded and checked.": "다시 압축한 ASTC 블록을 디코딩해 확인하지 못했습니다.",
    # Baked blush errors the server can return to the Save status (the texture
    # tools show the same wording from their own table).
    "No verified stock blush pattern (cheek_array) is available. Open another costume that contains it once (most costume bundles do) so it is kept automatically, then reopen this model.": "확인된 기본 홍조 무늬(cheek_array)가 없습니다. 홍조 무늬가 들어 있는 다른 의상을 한 번 열면 자동으로 보관되니(대부분의 의상 번들에 있음), 그다음 이 모델을 다시 여세요.",
    "Baked blush is available only for a head material's main texture or its recolour texture.": "홍조 굽기는 머리 재질의 메인 텍스쳐나 그 리컬러 텍스쳐에만 쓸 수 있습니다.",
    "The blush bake takes only a blush type, a strength and a save mode.": "홍조 굽기에는 홍조 종류, 세기, 저장 방식만 들어갈 수 있습니다.",
    "Choose a blush strength between 0 and 4.": "홍조 세기는 0보다 크고 4 이하로 정하세요.",
    "Choose the Ppo or Akarame blush type.": "홍조 종류를 Ppo 또는 Akarame 중에서 고르세요.",
    "This model has no head texture that can take a baked blush.": "이 모델에는 홍조를 구울 수 있는 머리 텍스쳐가 없습니다.",
    "The cheek array payload has an unexpected size.": "홍조 무늬(cheek_array) 데이터의 크기가 올바르지 않습니다.",
    "The blush image or cheek layer has unexpected dimensions.": "홍조를 구울 이미지나 홍조 무늬의 크기가 올바르지 않습니다.",
    "The saved texture mip levels failed exact reload validation.": "저장한 텍스쳐의 밉맵이 다시 읽기 검증을 통과하지 못했습니다.",
    "The texture edit operations are invalid.": "텍스쳐 편집 작업 목록이 올바르지 않습니다.",
    "Apply or cancel the texture preview before saving.": "텍스쳐 미리보기를 적용하거나 취소한 뒤 저장하세요.",
    "The texture editor is unavailable.": "텍스쳐 편집기를 사용할 수 없습니다.",
    "Apply or cancel the texture preview before changing motions.": "텍스쳐 미리보기를 적용하거나 취소한 뒤 모션을 변경하세요.",
})
_TABLES["ja"].update({
    "Open texture editor": "テクスチャエディターを開く",
    "Choose PNG image": "PNG画像を選択",
    "Choose texture project": "テクスチャ作業ファイルを選択",
    "Texture editor": "テクスチャエディター",
    "Costume colour": "衣装カラー",
    "Skin tone": "肌の色",
    "Texture painting": "テクスチャペイント",
    "Baked blush": "頬紅の焼き込み",
    # Baked blush save summary (viewer_texture_tools / texture_block_splice).
    "The baked blush was saved as exact pixels (lossless RGBA32): every texel it does not change keeps its value.": "頬紅を正確なピクセル（可逆RGBA32）で保存しました。頬紅が変えないピクセルはすべて元の値のままです。",
    "The baked blush kept the game's ASTC compression: only the blocks it touches were compressed again, and every other block keeps its original bytes.": "頬紅をゲームの圧縮形式（ASTC）のまま保存しました。頬紅がかかるブロックだけを再圧縮し、ほかのブロックは元のデータのままです。",
    "This texture is also painted, and painted pixels are always saved exactly, so its ASTC compression was not kept.": "このテクスチャはペイントでも編集されており、ペイントしたピクセルは常に正確に保存されるため、ASTC圧縮は保ちませんでした。",
    "This texture is not ASTC-compressed, so there was no ASTC compression to keep.": "このテクスチャはASTC圧縮ではないため、保つASTC圧縮がありません。",
    "The ASTC encoder is unavailable.": "ASTCエンコーダーを使用できません。",
    "The ASTC encoder could not be started.": "ASTCエンコーダーを起動できませんでした。",
    "The ASTC encoder could not re-encode the baked blocks.": "ASTCエンコーダーが頬紅のブロックを再圧縮できませんでした。",
    "The ASTC encoder returned unexpected data.": "ASTCエンコーダーが想定外のデータを返しました。",
    "Re-encoding the baked blocks took too long.": "頬紅のブロックの再圧縮に時間がかかりすぎました。",
    "Re-encoded blocks changed texels outside the baked area.": "再圧縮したブロックが頬紅の範囲外のピクセルまで変えました。",
    "Re-encoding the baked blocks would change alpha.": "頬紅のブロックを再圧縮するとアルファが変わります。",
    "The re-encoded blocks are not close enough to the bake.": "再圧縮したブロックが焼き込んだ頬紅と違いすぎます。",
    "The original ASTC data is shorter than its mip chain.": "元のASTCデータがミップマップの段数に足りません。",
    "Choose how to save the baked blush: exact pixels or the game's ASTC compression.": "頬紅の保存方法を、正確なピクセルかゲームの圧縮形式（ASTC）を保つかから選んでください。",
    "The re-encoded ASTC blocks could not be decoded and checked.": "再圧縮したASTCブロックをデコードして確認できませんでした。",
    # Baked blush errors the server can return to the Save status (the texture
    # tools show the same wording from their own table).
    "No verified stock blush pattern (cheek_array) is available. Open another costume that contains it once (most costume bundles do) so it is kept automatically, then reopen this model.": "検証済みの標準の頬紅パターン（cheek_array）がありません。頬紅パターンを含む別の衣装を一度開くと自動で保管されます（ほとんどの衣装バンドルに含まれます）。その後、このモデルを開き直してください。",
    "Baked blush is available only for a head material's main texture or its recolour texture.": "頬紅の焼き込みは頭マテリアルのメインテクスチャかそのカラー違いテクスチャにのみ使えます。",
    "The blush bake takes only a blush type, a strength and a save mode.": "頬紅の焼き込みに指定できるのは種類、強さ、保存方法だけです。",
    "Choose a blush strength between 0 and 4.": "頬紅の強さは0より大きく4以下にしてください。",
    "Choose the Ppo or Akarame blush type.": "頬紅の種類を Ppo か Akarame から選んでください。",
    "This model has no head texture that can take a baked blush.": "このモデルには頬紅を焼き込める頭テクスチャがありません。",
    "The cheek array payload has an unexpected size.": "頬紅パターン（cheek_array）のデータサイズが正しくありません。",
    "The blush image or cheek layer has unexpected dimensions.": "頬紅を焼き込む画像または頬紅パターンの大きさが正しくありません。",
    "The saved texture mip levels failed exact reload validation.": "保存したテクスチャのミップマップが再読み込みの検証に通りませんでした。",
    "The texture edit operations are invalid.": "テクスチャ編集の操作一覧が正しくありません。",
    "Apply or cancel the texture preview before saving.": "テクスチャのプレビューを適用または取り消してから保存してください。",
    "The texture editor is unavailable.": "テクスチャエディターを使用できません。",
    "Apply or cancel the texture preview before changing motions.": "テクスチャのプレビューを適用または取り消してからモーションを変更してください。",
})

# MV Studio editor lane B: inspector value controls and their export guards.
_MV_EDITOR_B_TRANSLATIONS = {
    "Colour": ("색", "色"),
    "Tint colour": ("틴트 색", "ティント色"),
    "Blend colour": ("블렌드 색", "ブレンド色"),
    "Ambient colour": ("환경광 색", "環境光の色"),
    "Ambient tint colour": ("환경광 틴트 색", "環境光のティント色"),
    "Rim light colour": ("림 라이트 색", "リムライトの色"),
    "Rim light intensity": ("림 라이트 강도", "リムライトの強さ"),
    "Rim light sharpness": ("림 라이트 선명도", "リムライトのシャープさ"),
    "Rim light direction (°)": ("림 라이트 방향 (°)", "リムライトの向き (°)"),
    "Ambient colour source": ("환경광 색 기준", "環境光の色の指定"),
    "Rim light colour source": ("림 라이트 색 기준", "リムライトの色の指定"),
    "Ambient colour member": ("환경광 색 기준 멤버", "環境光の色の基準メンバー"),
    "Rim light colour member": ("림 라이트 색 기준 멤버", "リムライトの色の基準メンバー"),
    "Colour source": ("색 기준", "色の指定"),
    "Custom colour": ("직접 지정한 색", "指定した色"),
    "Member colour": ("멤버 색", "メンバーカラー"),
    "Original member colour": ("원래 멤버 색", "元のメンバーカラー"),
    "Member position": ("멤버 위치", "メンバー位置"),
    "Member {n}": ("멤버 {n}", "メンバー{n}"),
    "Intensity": ("강도", "強さ"),
    "Sharpness": ("선명도", "シャープさ"),
    "Direction (°)": ("방향 (°)", "向き (°)"),
    "Speed": ("속도", "速度"),
    "Weight": ("가중치", "ウェイト"),
    "Mouth shape": ("입 모양", "口の形"),
    "Eye shape": ("눈 모양", "目の形"),
    "0 · vowel of the parameter name": ("0 · 매개변수 이름의 모음", "0 · パラメーター名の母音"),
    "{n} (not played in MVs)": ("{n} (MV에서 재생되지 않음)", "{n} (MVでは再生されません)"),
    "Look at": ("바라볼 대상", "見る対象"),
    "None": ("없음", "なし"),
    "Audience": ("관객", "観客"),
    "Fixed eye direction {n}": ("고정 시선 방향 {n}", "固定の視線方向 {n}"),
    "Split-screen camera {n}": ("분할 화면 카메라 {n}", "分割画面カメラ {n}"),
    "Value {n}": ("값 {n}", "値 {n}"),
    "Blush pattern": ("홍조 무늬", "頬紅パターン"),
    "Blush pattern 1": ("홍조 무늬 1", "頬紅パターン1"),
    "Blush pattern 2": ("홍조 무늬 2", "頬紅パターン2"),
    "Blush intensity": ("홍조 강도", "頬紅の強さ"),
    "Bloom intensity": ("블룸 강도", "ブルームの強さ"),
    "Threshold": ("임계값", "しきい値"),
    "Soft knee": ("소프트 니", "ソフトニー"),
    "Radius": ("반경", "半径"),
    "Anti-flicker": ("깜빡임 방지", "ちらつき防止"),
    "Focus distance (m)": ("초점 맞출 거리 (m)", "ピント距離 (m)"),
    "Aperture": ("조리개", "絞り"),
    "Focal length (mm)": ("렌즈 초점 거리 (mm)", "焦点距離 (mm)"),
    "Use the camera field of view": ("카메라 시야각 사용", "カメラの視野角を使う"),
    "Anti-aura": ("안티 오라", "アンチオーラ"),
    "Blur size": ("흐림 크기", "ぼかしの大きさ"),
    "Small": ("작게", "小"),
    "Medium": ("보통", "中"),
    "Large": ("크게", "大"),
    "Very large": ("매우 크게", "特大"),
    "Focus on the member": ("멤버에 초점 맞추기", "メンバーにピントを合わせる"),
    "Focus body part": ("초점 부위", "ピントを合わせる部位"),
    "Head (all)": ("머리 (전체)", "頭 (全体)"),
    "Face": ("얼굴", "顔"),
    "Hips": ("엉덩이", "腰"),
    "Neck": ("목", "首"),
    "Focus transition time (s)": ("초점 전환 시간 (초)", "ピントの切り替え時間 (秒)"),
    "Height offset (m)": ("높이 오프셋 (m)", "高さのオフセット (m)"),
    "Follow smoothing (s)": ("따라가기 완화 시간 (초)", "追従のなめらかさ (秒)"),
    "Shaft shape": ("빛줄기 모양", "光の筋の形"),
    "Shaft shape {n}": ("빛줄기 모양 {n}", "光の筋の形 {n}"),
    "Centre": ("중심", "中心"),
    "Smoothness": ("부드러움", "なめらかさ"),
    "Roundness": ("둥근 정도", "丸み"),
    "Rounded": ("둥글게", "丸める"),
    "Flash lights": ("플래시 조명", "フラッシュライト"),
    "On": ("켜기", "オン"),
    "Scroll speed": ("스크롤 속도", "スクロール速度"),
    "Screen material": ("화면 머티리얼", "画面のマテリアル"),
    "Screen material {n}": ("화면 머티리얼 {n}", "画面のマテリアル {n}"),
    "Palette shift": ("팔레트 이동", "パレットのずらし"),
    "Light texture": ("조명 텍스처", "ライトのテクスチャ"),
    "Light texture {n}": ("조명 텍스처 {n}", "ライトのテクスチャ {n}"),
    "Offset strength": ("오프셋 강도", "オフセットの強さ"),
    "Fog intensity": ("안개 강도", "フォグの強さ"),
    "Random brightness": ("무작위 밝기", "ランダムな明るさ"),
    "Beat length": ("박자 길이", "拍の長さ"),
    "Beat offset": ("박자 오프셋", "拍のオフセット"),
    "Random delay": ("무작위 지연", "ランダムな遅延"),
    "Random rise": ("무작위 올림", "ランダムな上げ"),
    "Random swing strength": ("무작위 흔들기 강도", "ランダムな振りの強さ"),
    "Offset (m)": ("오프셋 (m)", "オフセット (m)"),
    "Scaling strength": ("키 보정 강도", "身長補正の強さ"),
    "Not shown in the preview": ("미리보기에 표시되지 않음", "プレビューに表示されません"),
    "This value is exported to the game, but the 3D preview does not show it.": (
        "이 값은 게임으로 내보내지지만 3D 미리보기에는 표시되지 않습니다.",
        "この値はゲームに書き出されますが、3Dプレビューには表示されません。"),
    "Exact values": ("정확한 값", "正確な値"),
    "{label}: intensity": ("{label}: 강도", "{label}: 強さ"),
    "Intensity (×): the colour's brightest channel, shown as 1 when it is lower. An entry of 1 or more scales the colour so that channel equals it. Pick a darker colour on the swatch.": (
        "강도 (×): 색에서 가장 밝은 채널의 값이며, 1보다 낮으면 1로 표시됩니다. 1 이상을 입력하면 그 채널이 입력값이 되도록 색 전체를 같은 비율로 조정합니다. 더 어두운 색은 견본에서 고르세요.",
        "強さ (×): 色の最も明るいチャンネルの値で、1未満のときは1と表示されます。1以上を入力すると、そのチャンネルが入力値になるよう色全体を同じ比率で調整します。より暗い色は見本で選んでください。"),
    "Native data (read only)": ("원본 데이터 (읽기 전용)", "元データ (読み取り専用)"),
    "Playable asset": ("플레이어블 에셋", "Playableアセット"),
    "Playable class": ("플레이어블 클래스", "Playableクラス"),
    "Animation clip": ("애니메이션 클립", "アニメーションクリップ"),
    "Animation name": ("애니메이션 이름", "アニメーション名"),
    "Mix-in curve": ("믹스 인 곡선", "ミックスインカーブ"),
    "Mix-out curve": ("믹스 아웃 곡선", "ミックスアウトカーブ"),
    "Effect prefab": ("이펙트 프리팹", "エフェクトのプレハブ"),
    "Particle random seed": ("파티클 랜덤 시드", "パーティクルの乱数シード"),
    "Overwrite random seed": ("랜덤 시드 덮어쓰기", "乱数シードを上書き"),
    # Export guards (mv_studio_timeline._check_values).
    "Choose a value this MV already uses for 'textureIndex'.": (
        "이 MV에서 이미 쓰는 'textureIndex' 값 중에서 고르세요.", "このMVですでに使われている'textureIndex'の値から選んでください。"),
    "Choose a value this MV already uses for 'materialIndex'.": (
        "이 MV에서 이미 쓰는 'materialIndex' 값 중에서 고르세요.", "このMVですでに使われている'materialIndex'の値から選んでください。"),
    "Choose a value this MV already uses for 'drawObjectIndex'.": (
        "이 MV에서 이미 쓰는 'drawObjectIndex' 값 중에서 고르세요.", "このMVですでに使われている'drawObjectIndex'の値から選んでください。"),
    "Choose a value this MV already uses for 'bodyPart'.": (
        "이 MV에서 이미 쓰는 'bodyPart' 값 중에서 고르세요.", "このMVですでに使われている'bodyPart'の値から選んでください。"),
    "This colour source needs the clip's member position to be 1 to 12.": (
        "이 색 기준을 쓰려면 클립의 멤버 위치가 1~12여야 합니다.",
        "この色の指定を使うには、クリップのメンバー位置が1〜12である必要があります。"),
    "Member focus needs the clip's member position to be 1 to 12.": (
        "멤버에 초점을 맞추려면 클립의 멤버 위치가 1~12여야 합니다.",
        "メンバーにピントを合わせるには、クリップのメンバー位置が1〜12である必要があります。"),
}
for _source, (_korean, _japanese) in _MV_EDITOR_B_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# MV Studio export slots (mv_studio_timeline): track mutes that reach the game, their plan lines
# (mv-studio-apply.js, mv-studio-register.js) and export refusals.
_MV_EXPORT_SLOT_TRANSLATIONS = {
    "Tracks muted or unmuted: {count}": ("음소거를 바꾼 트랙: {count}개", "ミュートを切り替えたトラック: {count}"),
    "Apply all: {count} track mutes differ from the original MV": (
        "전체 적용: 원본 MV와 음소거가 다른 트랙 {count}개", "全体を適用: 元のMVとミュートが異なるトラック{count}個"),
    "A group track's mute does not reach the game. Mute the tracks inside it.": (
        "그룹 트랙의 음소거는 게임에 반영되지 않습니다. 그 안의 트랙을 음소거하세요.",
        "グループトラックのミュートはゲームに反映されません。中のトラックをミュートしてください。"),
    "The game's quality settings turn this track on and off, so its mute does not reach the game.": (
        "이 트랙은 게임의 품질 설정이 켜고 끄므로 음소거가 게임에 반영되지 않습니다.",
        "このトラックはゲームの画質設定でオン・オフが決まるため、ミュートはゲームに反映されません。"),
    "The game turns eye and mouth tracks on and off itself, so this mute does not reach the game.": (
        "눈과 입 트랙은 게임이 직접 켜고 끄므로 이 음소거는 게임에 반영되지 않습니다.",
        "目と口のトラックはゲームが自分でオン・オフを決めるため、このミュートはゲームに反映されません。"),
    "A track mute must be on or off.": ("트랙 음소거는 켜기나 끄기로만 정할 수 있습니다.", "トラックのミュートはオンかオフで指定してください。"),
    "This native track has no mute to change.": ("이 원본 트랙에는 바꿀 수 있는 음소거가 없습니다.", "この元のトラックには変更できるミュートがありません。"),
    # Member targets (mv-studio-event-fields.js descriptors, mv_studio_timeline.MEMBER_SLOT).
    "Focus member": ("초점 맞출 멤버", "ピントを合わせるメンバー"),
    "Focus target": ("초점 대상", "ピントの対象"),
    "The chosen member": ("지정한 멤버", "指定したメンバー"),
    "The nearest member": ("가장 가까운 멤버", "いちばん近いメンバー"),
    "The member nearest the centre": ("화면 중앙에 가장 가까운 멤버", "画面の中央にいちばん近いメンバー"),
    "Colour member": ("색 기준 멤버", "色の基準メンバー"),
    "Height from member": ("높이 기준 멤버", "高さの基準メンバー"),
    "Choose a member this MV has.": ("이 MV에 있는 멤버를 고르세요.", "このMVにいるメンバーを選んでください。"),
    # Penlight crowd motion (LivePenlightClip descriptors and export guards).
    "Swing motion": ("흔들기 동작", "振りの動き"),
    "Penlight colours": ("펜라이트 색", "ペンライトの色"),
    "Colour {n}": ("색 {n}", "色 {n}"),
    "Still": ("멈춤", "止める"),
    "Front-back swing": ("앞뒤 흔들기", "前後の振り"),
    "Rising swing": ("올려 흔들기", "持ち上げる振り"),
    "Side swing": ("좌우 흔들기", "左右の振り"),
    "Sway": ("살랑 흔들기", "ゆらゆら揺らす"),
    "Crowd position (m)": ("관객 위치 (m)", "観客の位置 (m)"),
    "Front-back swing: lift (m)": ("앞뒤 흔들기: 올림 (m)", "前後の振り: 上げ幅 (m)"),
    "Front-back swing: reach (m)": ("앞뒤 흔들기: 앞으로 뻗기 (m)", "前後の振り: 前への幅 (m)"),
    "Front-back swing: tilt (rad)": ("앞뒤 흔들기: 기울기 (rad)", "前後の振り: 傾き (rad)"),
    "Front-back swing: rest point": ("앞뒤 흔들기: 기준 위치", "前後の振り: 基準の位置"),
    "Front-back swing: snap": ("앞뒤 흔들기: 끊어 치기", "前後の振り: キレ"),
    "Rising swing: lift (m)": ("올려 흔들기: 올림 (m)", "持ち上げる振り: 上げ幅 (m)"),
    "Rising swing: reach (m)": ("올려 흔들기: 앞으로 뻗기 (m)", "持ち上げる振り: 前への幅 (m)"),
    "Rising swing: tilt (rad)": ("올려 흔들기: 기울기 (rad)", "持ち上げる振り: 傾き (rad)"),
    "Rising swing: rest point": ("올려 흔들기: 기준 위치", "持ち上げる振り: 基準の位置"),
    "Rising swing: snap": ("올려 흔들기: 끊어 치기", "持ち上げる振り: キレ"),
    "Rising swing: turn point": ("올려 흔들기: 전환 지점", "持ち上げる振り: 切り替えの位置"),
    "Rising swing: lift curve": ("올려 흔들기: 올림 곡선", "持ち上げる振り: 上げのカーブ"),
    "Side swing: tilt (rad)": ("좌우 흔들기: 기울기 (rad)", "左右の振り: 傾き (rad)"),
    "Side swing: reach (m)": ("좌우 흔들기: 옆으로 뻗기 (m)", "左右の振り: 横への幅 (m)"),
    "Side swing: lift (m)": ("좌우 흔들기: 올림 (m)", "左右の振り: 上げ幅 (m)"),
    "Sway: side tilt (rad)": ("살랑 흔들기: 좌우 기울기 (rad)", "ゆらゆら揺らす: 左右の傾き (rad)"),
    "Sway: front tilt (rad)": ("살랑 흔들기: 앞뒤 기울기 (rad)", "ゆらゆら揺らす: 前後の傾き (rad)"),
    "Keep the penlight colour list's length and fields.": (
        "펜라이트 색 목록의 길이와 항목은 그대로 두세요.", "ペンライトの色リストの長さと項目はそのままにしてください。"),
}
# Range refusals of the native export for each bounded field (mv_studio_timeline._LIMITED_VALUES and
# _FLOAT_RANGES; tests/test_mv_studio_editable_values.py pins these lists to them). The UI bounds its
# inputs, so only a hand-edited or API project meets them.
for _field in ("index", "target", "cheekType", "colorSpecifiedType", "kernelSize", "useMemberDistance",
               "cameraAutoDistanceMode", "ambientColorType", "rimlightColorType", "status", "swingMode"):
    _MV_EXPORT_SLOT_TRANSLATIONS[f"'{_field}' is outside the supported native range."] = (
        f"'{_field}' 값이 지원하는 원본 범위를 벗어났습니다.", f"'{_field}'の値が対応する元の範囲を外れています。")
for _field in ("focusTransitionTime", "basicYZMoveY", "basicYZMoveZ", "basicYZRotateZ", "basicYZSwingBackZ",
               "basicYZSwingPowerZ", "growthYZMoveY", "growthYZMoveZ", "growthYZRotateZ", "growthYZSwingBackZ",
               "growthYZSwingPowerZ", "growthYZSwingBottomZ", "basicXRotateX", "basicXMoveX", "basicXMoveY",
               "simpleXZRotateX", "simpleXZRotateZ"):
    _MV_EXPORT_SLOT_TRANSLATIONS[f"The timeline has an invalid {_field}."] = (
        f"타임라인의 '{_field}' 값이 올바르지 않습니다.", f"タイムラインの'{_field}'の値が正しくありません。")
# Refusals of a vector value (mv_studio_timeline._replace_value): a missing or extra axis, or an axis
# beyond ±1e6, which a typed number box can reach. These are the fields with a "vector" control in
# mv-studio-event-fields.js (the test pins the list to the descriptor table).
for _field in ("center", "direction", "offset", "position", "randomDelay", "randomUp", "rimlightDirection", "scale",
               "scrollSpeed"):
    _MV_EXPORT_SLOT_TRANSLATIONS[f"'{_field}' is not a supported native value for this clip."] = (
        f"'{_field}' 값은 이 클립에서 지원하지 않는 원본 값입니다.", f"'{_field}'の値はこのクリップで対応していない元の値です。")
    _MV_EXPORT_SLOT_TRANSLATIONS[f"The timeline has an invalid {_field}."] = (
        f"타임라인의 '{_field}' 값이 올바르지 않습니다.", f"タイムラインの'{_field}'の値が正しくありません。")
for _source, (_korean, _japanese) in _MV_EXPORT_SLOT_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# MV Studio layout: the stage / side panel splitter and the side panel toggle (mv-studio.js
# setupInspectorResizer). "Hidden" is the splitter's value text while the panel is folded.
_MV_LAYOUT_TRANSLATIONS = {
    "Side panel": ("사이드 패널", "サイドパネル"),
    "Panel width": ("패널 너비", "パネルの幅"),
    "Panel height": ("패널 높이", "パネルの高さ"),
    "Drag, or use the arrow keys, to share the room between the stage and the panel. Home restores the default, End gives the panel its largest size, Enter hides or shows the panel.": (
        "드래그하거나 화살표 키로 무대와 패널의 크기를 조절합니다. Home 키는 기본 크기로, End 키는 패널을 최대 크기로 바꾸며, Enter 키는 패널을 숨기거나 다시 표시합니다.",
        "ドラッグするか矢印キーで、ステージとパネルの大きさを調整します。Homeキーで標準の大きさに戻し、Endキーでパネルを最大にし、Enterキーでパネルを隠す・再表示します。",
    ),
}
for _source, (_korean, _japanese) in _MV_LAYOUT_TRANSLATIONS.items():
    _TABLES["ko"][_source] = _korean
    _TABLES["ja"][_source] = _japanese

# Readable model names (model_labels.py, model-viewer.js, viewer-persistence.js):
# the game's member and costume names replace cache file names wherever a
# person reads them. The automatic Mod name's edit labels are also built by
# the server for each installed language, so every label it uses is here.
_MODEL_LABEL_TRANSLATIONS = {
    "Costume #{id}": ("의상 #{id}", "衣装 #{id}"),
    "Face (automatic)": ("얼굴(자동)", "顔（自動）"),
    "File": ("파일", "ファイル"),
    "{region} costume ID {id}": ("{region} 의상 ID {id}", "{region} 衣装ID {id}"),
    "Costume transplant": ("코스튬 이식", "衣装移植"),
    "Costume part transplant": ("코스튬 부분 이식", "衣装パーツ移植"),
    "Lower body replacement": ("하체 교체", "下半身の交換"),
    "Mesh editing": ("메시 편집", "メッシュ編集"),
    "Mesh deletion": ("메시 삭제", "メッシュ削除"),
    "Physics": ("물리", "物理"),
    # Refusals of the labels route and the Mod ZIP's name/record checks.
    "Choose between one and sixteen model files.": ("모델 파일을 1~16개 선택해주세요.", "モデルファイルを1～16個選んでください。"),
    "The model file is empty or too large to label.": (
        "모델 파일이 비어 있거나 너무 커서 이름을 표시할 수 없습니다.", "モデルファイルが空か大きすぎるため、名前を表示できません。"),
    "The model file changed while it was labelled.": (
        "이름을 읽는 동안 모델 파일이 바뀌었습니다.", "名前を読み取っている間にモデルファイルが変わりました。"),
    "The per-language costume names are incomplete.": (
        "언어별 의상 이름이 일부 빠져 있습니다.", "言語ごとの衣装名が一部足りません。"),
    "The source costume record is invalid.": ("원본 의상 기록이 올바르지 않습니다.", "元の衣装の記録が無効です。"),
    "The source costume record changed.": ("원본 의상 기록이 바뀌었습니다.", "元の衣装の記録が変わりました。"),
}
for _source, (_korean, _japanese) in _MODEL_LABEL_TRANSLATIONS.items():
    _TABLES["ko"].setdefault(_source, _korean)
    _TABLES["ja"].setdefault(_source, _japanese)
