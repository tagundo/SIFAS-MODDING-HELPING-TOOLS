# 립싱크를 더 스마트하게 — 조사 노트

`live_timeline/` 5단계 파이프라인을 코드까지 분석하고, 더 똑똑하게 만들 방법을
조사했습니다. 결론부터: **두 갈래의 개선**이 있습니다 — ① 지금 방식(SCD 변환)을
견고하게, ② 아예 오디오에서 자동 생성(새 곡용).

---

## 1. 지금 "맞추는" 방식은 사실 *변환*이지 *생성*이 아니다

현재 파이프라인은 오디오를 듣고 입을 만드는 게 아니라, **SIFAC 게임이 이미 만들어 둔
립싱크 데이터(`.scd`)를 SIFAS 입모양으로 옮기는 트랜스코딩**입니다.

| 단계 | 파일 | 하는 일 |
|---|---|---|
| 1 | `1_scd-lyrics-analyzer` | `.scd`(매직 `Scor`, 32B 엔트리: start_ms·dur_ms·char_id·3글자 음소) → 텍스트 리포트 |
| 2 | `2_scd_renumber` | 수동 삭제 후 번호 재정렬(사람이 큐레이션) |
| 3 | `3_import_to_mouth_gui4` | 음소→입모양(A/I/U/E/O/N) 매핑, UABEA 텍스트 덤프의 `m_Start`/`m_Duration`/`m_DisplayName` 교체 |
| 4 | `4_timeline_fixer2` | 커브/이즈 정규화 |
| 5 | `5_unitypy_...import` | UnityPy로 번들에 재주입(**TypeTree 직접 편집**) |

### 코드에서 드러난 "안 스마트한" 지점

1. **음소 매핑이 화이트리스트(3번 줄 15–23).** `ada/iri/uyu...` 약 30개만 하드코딩,
   목록에 없으면 `.get(phon,"A")`로 **전부 조용히 "A"가 됨.** 사전에 없는 음소 = 무조건
   틀린 입모양. → 일본어는 모든 모라가 모음으로 끝나므로 **규칙 기반(모음 추출)** 으로
   100% 커버 가능한데, 굳이 열거형이라 취약.
2. **텍스트 왕복이 깨지기 쉬움.** 1→2→3→4가 사람이 읽는 `.txt` 리포트를 정규식으로 다시
   파싱하는 다단계(LINE_RE 등). 포맷이 조금만 달라도 `⚠️ doesn't match`. 그런데 **5번은
   이미 UnityPy `read_typetree`/`save_typetree`로 직접 편집**을 증명함 → 3·4번의 텍스트
   편집을 TypeTree 직접 편집으로 대체하면 실패 지점이 대부분 사라짐.
3. **오디오 경로가 전혀 없음.** `.scd`가 없는 곡(신곡/창작)이면 손으로 다 찍어야 함. ← 가장 큰 공백.
4. **타이밍이 그대로 복사.** 최소 유지시간/미세 비짐 병합/자음·쉼에서 입닫기(코아티큘레이션)
   없음 → 빠른 구간에서 입이 떨릴 수 있음.
5. **캐릭터 중복.** `.scd`는 char_id별로 들어있는데 타깃은 입 하나 → 한 스트림 선택/병합 필요.

---

## 2. 핵심 통찰: 일본어는 비짐(viseme) 문제가 쉽다

SIFAS 입모양은 **A·I·U·E·O·N 6종**. 일본어는 **모음 5개 + 발음 N**이 전부이고 모든 모라가
모음으로 끝납니다. 즉 **음소→입모양이 1:1**. 영어처럼 자음 비짐(F/V, L, MBP…)을 더 둘
필요가 없습니다. 그래서 "음소를 뽑아 모음으로 환원"만 정확하면 어디서 음소를 얻든(.scd,
가사 텍스트, 오디오) 일본어 립싱크는 충분히 정확합니다.

---

## 3. 더 스마트하게 — 두 갈래

### A. 지금 SCD 경로를 견고하게 (적은 노력, 큰 효과)

1. **규칙 기반 모라→모음 리듀서**로 화이트리스트 교체:
   음소 코드에서 모음 글자(a/i/u/e/o)를 뽑아 그 입모양으로, `n`/`nn`→N, 장음·촉음(っ)·무음→
   직전 모음 유지 또는 입닫기. **미지 음소 0%**, 조용한 "A" 폴백 제거.
2. **텍스트 왕복 제거**: `LiveTimelineData`의 mouth TimelineClip을 UnityPy TypeTree로
   바로 써서 `m_Start`/`m_Duration`/`m_DisplayName`을 한 번에 기입(5번 확장). 3·4번 불필요.
3. **타이밍 후처리**: 최소 유지시간, 짧은 비짐 병합, 쉼/장자음에서 입닫기 삽입 → 자연스러움↑.
4. **결과 미리보기**: 입모양 타임라인 vs 오디오 파형/가사 정렬을 한 장 PNG로 검수.

→ 5개 GUI 단계를 **`scd → 완성 번들` 한 방 CLI**로 통합 가능.

### B. 오디오 자동 생성 (진짜 "스마트", 신곡용)

곡 음원만(또는 +가사) 있으면 입을 자동 생성. 일본어 비짐이 쉬우므로 정확도 높음.

| 가진 것 | 추천 도구 | 방식 |
|---|---|---|
| **가사 텍스트 O** (가장 정확) | **narabas**(JP 전용, Wav2Vec2/ReazonSpeech) 또는 **MFA + pyopenjtalk** | 가사 → pyopenjtalk로 음소열 → 오디오와 **강제정렬** → 음소별 타임스탬프 → 모음 환원 → 입모양 |
| **가사 없음** | **Rhubarb Lip Sync**(CLI, 6–9 입모양, 비영어 phonetic 인식) 또는 **Allosaurus**(2000+ 언어, 텍스트 불필요) / Wav2Vec2Phoneme | 오디오 → 음소/비짐 직접 추정 → 모음 환원 → 입모양 |

- **narabas/MFA**: 가사를 알 때 가장 정확(보컬 분리 후 강제정렬 권장).
- **Rhubarb**: 가장 간단(설치 한 번, CSV 출력). 기본 6입모양이 SIFAS 6종과 바로 대응.
- **Allosaurus/Wav2Vec2Phoneme**: 가사 없이 음소 인식. 노이즈에 더 취약하니 보컬 분리 권장.

### C. 검증 스마트
신뢰도 플래그(저신뢰 구간 표시), 파형-비짐 정렬 미리보기, 1-샷 CLI(GUI 5단계 대체).

---

## 권장 우선순위

1. **규칙 기반 모라→모음 매퍼 + TypeTree 직접 기입** — 화이트리스트/텍스트왕복 제거.
   기존 `.scd` 자산에 즉시 효과, 위험 최소. *(작은 작업, 가장 먼저)*
2. **가사+오디오 강제정렬 경로**(narabas 또는 MFA+pyopenjtalk) — `.scd` 없는 곡까지 커버.
3. **Rhubarb 폴백**(가사도 없을 때) + 파형-비짐 미리보기.

> 셋 다 일본어의 "모음=입모양 1:1" 덕분에 자음 비짐 없이 충분히 정확합니다.

---

## 출처

- 현재 파이프라인: `live_timeline/1..5_*.py`(이 저장소)
- Rhubarb Lip Sync: <https://github.com/DanielSWolf/rhubarb-lip-sync>
- Montreal Forced Aligner: <https://montreal-forced-aligner.readthedocs.io/>
- narabas (JP 음소 강제정렬): <https://github.com/darashi/narabas>
- pyopenjtalk(G2P), haqumei: <https://pypi.org/project/pyopenjtalk/> · <https://github.com/o24s/haqumei>
- Allosaurus(보편 음소 인식): <https://github.com/xinjli/allosaurus>
- Wav2Vec2Phoneme: <https://huggingface.co/docs/transformers/model_doc/wav2vec2_phoneme>
