"""Localized MV quality controls backed by the game's selected stage preset.

    Resolution and frame rate set the render budget. Stage flags apply to the
    stage, its effect bundle and the timeline. Member and prop flags control
    their own models and lighting. Split screen follows the authored timeline.
    The stock 2D mode has a separate settings set.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

from . import game_models as game


_LANGUAGES = {"en": 0, "ko": 1, "ja": 2}
_NORMAL_3D = 30
_STOCK_2D = 50
_TWO_DIMENSIONS = "k.m_live_quality_mode_2d"

# SQL names and ordering match m_live_quality_setting. Each tuple holds the
# English, Korean and Japanese labels for the controls specific to Studio.
_FIELDS = {
    "rendering_resolution": ("Render resolution", "렌더링 해상도", "描画解像度"),
    "frame_rate_60fps": ("60 fps", "60fps", "60fps"),
    "base_light": ("Base lighting", "기본 조명", "基本照明"),
    "stage_ambient": ("Stage ambient lighting", "무대 환경광", "ステージ環境光"),
    "stage_animation": ("Stage animation", "무대 애니메이션", "ステージアニメーション"),
    "stage_coloring": ("Stage coloring", "무대 색상 연출", "ステージの色演出"),
    "stage_control": ("Stage controls", "무대 제어", "ステージ制御"),
    "stage_overlay_effect": ("Stage overlay effects", "무대 오버레이 효과", "ステージのオーバーレイ効果"),
    "stage_flash_light": ("Stage flash lighting", "무대 점멸 조명", "ステージの点滅照明"),
    "stage_display": ("Stage displays", "무대 화면", "ステージのスクリーン"),
    "posteffect": ("Post-processing effects", "후처리 효과", "ポストエフェクト"),
    "stage_emissive": ("Stage emissive surfaces", "무대 발광 표면", "ステージの発光面"),
    "stage_audience": ("Audience", "관객", "観客"),
    "stage_cubemap": ("Stage environment reflections", "무대 환경 반사", "ステージの環境反射"),
    "member_ambient": ("Performer ambient lighting", "멤버 환경광", "メンバー環境光"),
    "member_rim_light": ("Performer rim lighting", "멤버 윤곽광", "メンバーのリムライト"),
    "member_spot_light_shaft": ("Performer spotlight beams", "멤버 스포트라이트 빛줄기", "メンバーのスポットライト光線"),
    "member_spot_light_area": ("Performer spotlight areas", "멤버 스포트라이트 영역", "メンバーのスポットライト範囲"),
    "member_swing_bone_live": ("Swing physics in Live Shows", "라이브 흔들림 물리", "ライブの揺れ物理"),
    "member_swing_bone_mv": ("Swing physics in MVs", "MV 흔들림 물리", "MVの揺れ物理"),
    "prop_ambient": ("Prop ambient lighting", "소품 환경광", "小道具の環境光"),
    "prop_rim_light": ("Prop rim lighting", "소품 윤곽광", "小道具のリムライト"),
    "split_screen": ("Split-screen cameras", "분할 화면 카메라", "分割画面カメラ"),
}
_DESCRIPTIONS = {
    "rendering_resolution": ("Internal render height in pixels.", "내부 렌더링 높이(픽셀)입니다.", "内部描画の高さをピクセルで指定します。"),
    "frame_rate_60fps": ("Requests 60 frames per second for the live scene.", "라이브 장면을 초당 60프레임으로 설정합니다.", "ライブシーンを毎秒60フレームに設定します。"),
    "member_swing_bone_live": ("Uses the swing setting for the playable rhythm game.", "리듬 게임을 플레이할 때의 흔들림 설정입니다.", "リズムゲームをプレイするときの揺れ設定です。"),
    "member_swing_bone_mv": ("Uses the swing setting for the MV scene.", "MV 장면의 흔들림 설정입니다.", "MVシーンの揺れ設定です。"),
    "split_screen": ("Uses the split-camera tracks where the timeline defines them.", "타임라인에 지정된 분할 화면 카메라를 사용합니다.", "タイムラインで指定された分割カメラを使用します。"),
}
_2D_HELP = (
    "Choose a 3D quality mode to render the stage and performers.",
    "무대와 멤버를 3D로 렌더링하려면 3D 품질을 선택하세요.",
    "ステージとメンバーを描画するには3D画質を選んでください。",
)
_MODE_LABELS = {
    10: ("Max 3D", "3D 매우 높음", "3D最高"),
    20: ("High 3D", "3D 높음", "3D高"),
    30: ("Normal 3D", "3D 보통", "3D通常"),
    40: ("Performance 3D", "3D 경량", "3D軽量"),
    50: ("2D", "2D", "2D"),
}


def _dictionary_text(dictionary, key):
    if not isinstance(key, str):
        return ""
    if dictionary is None or not key.startswith("k."):
        return key if not key.startswith("k.") else ""
    try:
        row = dictionary.execute("SELECT message FROM m_dictionary WHERE id=?", (key[2:],)).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        return ""
    return row[0] if row and isinstance(row[0], str) else ""


def _values(row):
    values = {"set_id": row["set_id"], "quality_mode": row["quality_mode"]}
    for key in _FIELDS:
        value = row[key]
        if key == "rendering_resolution":
            if type(value) is not int or value <= 0:
                raise ValueError("The game preset has an invalid render resolution.")
        elif type(value) is not int or value not in (0, 1):
            raise ValueError("The game preset has an invalid graphics setting.")
        values[key] = value if key == "rendering_resolution" else bool(value)
    return values


def _read_rows(repo_root, region, quality_set):
    with closing(game._readonly(Path(repo_root) / "assets/db" / region / "masterdata.db")) as db:
        db.row_factory = sqlite3.Row
        modes = db.execute("SELECT quality_mode,name,description,dimension_name FROM m_live_quality_mode "
                           "ORDER BY system_index,quality_mode").fetchall()
        if quality_set is None:
            row = db.execute("SELECT MIN(s.set_id) FROM m_live_quality_setting s "
                             "JOIN m_live_quality_mode m ON m.quality_mode=s.quality_mode "
                             "WHERE m.quality_mode<>? AND m.dimension_name<>?", (_STOCK_2D, _TWO_DIMENSIONS)).fetchone()
            quality_set = row[0]
        selected = db.execute("SELECT * FROM m_live_quality_setting WHERE set_id=? ORDER BY quality_mode",
                              (quality_set,)).fetchall()
        if not selected:
            raise ValueError("The selected stage quality preset is unavailable.")
        rows = {row["quality_mode"]: row for row in selected}
        for mode in modes:
            identity = mode["quality_mode"]
            if identity not in rows and (identity == _STOCK_2D or mode["dimension_name"] == _TWO_DIMENSIONS):
                row = db.execute("SELECT * FROM m_live_quality_setting WHERE quality_mode=? ORDER BY set_id LIMIT 1",
                                 (identity,)).fetchone()
                if row:
                    rows[identity] = row
    return modes, rows


def read_quality(repo_root, *, region, language, quality_set=None):
    """Return stage-specific native modes, defaults, and the form's editable controls."""
    if quality_set is not None and (type(quality_set) is not int or not 0 < quality_set <= 0x7FFFFFFF):
        raise ValueError("Choose a valid stage quality preset.")
    if language not in ("en", "ko", "ja", "zh"):
        language = "en"
    region, _ = game._region(repo_root, region, language)
    column = _LANGUAGES.get(language, 0)
    try:
        modes, rows = _read_rows(repo_root, region, quality_set)
        dictionary = game._dictionary(repo_root, region, language)
        options = []
        choices = []
        try:
            for mode in modes:
                identity = mode["quality_mode"]
                if identity not in rows:
                    continue
                label = _dictionary_text(dictionary, mode["name"]) or _MODE_LABELS.get(identity, (str(identity),) * 3)[column]
                description = _dictionary_text(dictionary, mode["description"])
                if identity == _STOCK_2D or mode["dimension_name"] == _TWO_DIMENSIONS:
                    description = " ".join(filter(None, (description, _2D_HELP[column])))
                choices.append({"id": identity, "label": label, "description": description, "values": _values(rows[identity])})
        finally:
            if dictionary is not None:
                dictionary.close()
        if not choices:
            raise ValueError("The selected stage has no usable game quality modes.")
    except (IndexError, sqlite3.Error) as exc:
        raise ValueError("The game quality catalog is unavailable or incomplete.") from exc
    for key, labels in _FIELDS.items():
        field = {"key": key, "label": labels[column], "type": "number" if key == "rendering_resolution" else "boolean"}
        if key in _DESCRIPTIONS:
            field["description"] = _DESCRIPTIONS[key][column]
        options.append(field)
    selected = next((choice for choice in choices if choice["id"] == _NORMAL_3D), choices[0])
    return {"modes": choices, "options": options, "mode": selected["id"], "values": dict(selected["values"])}
