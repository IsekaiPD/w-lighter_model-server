# API_CONTRACT — w-lighter MODEL 서버 (FastAPI)

WEB(Django)이 호출하는 MODEL 서버의 HTTP 계약. **실제 코드(`domains/*/router.py`·`schemas.py`)에서 도출한 정본**이며,
스키마 변경 시 이 문서를 같은 작업에서 갱신한다. 인터랙티브 탐색은 `GET /docs`(Swagger UI) 참고.

## 호출 구조 (안 A)

```
[브라우저] → Django(WEB) → FastAPI(MODEL)   ← 서버-대-서버 (CORS 무관)
```

- 브라우저는 MODEL 서버를 직접 부르지 않는다. **Django가 프록시**해서 호출한다.
- 인증·크레딧 차감·rate limit은 **Django(WEB) 측에서** 처리. MODEL 서버는 내부망 전용(외부 비공개).
- 내부 토큰(Django↔FastAPI 공유 시크릿 헤더)은 연동 실배선 시 추가 예정(현재 미구현).

## 공통 규약

- **Base URL**: 배포 내부망 기준 `http://<model-host>:8000`. 도메인 엔드포인트 prefix = `/api/v1`.
- **요청/응답**: JSON (`Content-Type: application/json`). 한국어 원문은 UTF-8.
- **요청 추가 키**: 대부분 `extra=ignore`(미정의 키 무시), `guide`만 `extra=allow`(엔진이 직접 사용).
- **응답 추가 키**: 대부분 `extra=allow` — 아래 표는 **보장되는 키**이고, 엔진이 키를 더 실어 보낼 수 있다. 단, `guide` 공개 응답은 프론트 표시용 HTML 중심 필드로 정리한다.

### 공통 에러 형식

| 상태 | 형식 | 발생 |
|---|---|---|
| `400` | `{"ok": false, "errorCode": "<code>", "message": "<설명>"}` | 잘못된 입력(빈 값/로케일 정규화 실패 등). `errorCode`=`invalid_request` 또는 로케일 에러코드 |
| `422` | `{"detail": [ ... ]}` (FastAPI 기본) | 스키마 검증 실패(필수 필드 누락/타입 불일치/범위 초과) |
| `503` | `{"ok": false, "errorCode": "engine_not_ready", "message": "<설명>"}` | 엔진 미준비(Qdrant/KURE/OpenAI 키 미설정 등). 구성 단계에선 정상 |

> 참고: `400`은 도메인 검증(서비스/엔진이 던지는 `ValueError`), `422`는 Pydantic 스키마 검증. 둘 다 "입력 문제"지만 형식이 다름.

---

### DB 영속화 (공통 패턴)

AI 산출물을 DB(MySQL/SQLite)에 저장하는 엔드포인트는 **공통 규칙**을 따른다(구조 A: 보통 Django가 `workId`/`translationId`를 넘김).

- 저장은 **식별자 + save 플래그 + rdb 백엔드** 3박자가 맞아야 동작한다:
  `workId`(또는 inspect-chat은 `translationId`)가 있고 + `save*` 플래그가 `true`(기본)고 + 서버가 `CONTENT_STORE_BACKEND=rdb`일 때.
- 셋 중 하나라도 빠지면 **graceful no-op**(저장만 건너뜀, 본 응답은 정상). 예: `workId` 없음 → 저장 안 함, memory 백엔드 → 안 함.
- 저장을 시도하면 응답에 **`persisted*` 키**가 붙는다(`{saved: bool, ...id}` 또는 실패 사유). best-effort라 저장 실패해도 본 산출물은 200으로 반환된다.
- write 경계: **works/episodes(작품/회차)는 WEB(Django)이 생성**, 모델 서버는 AI 산출물(translation_results·characters·relation_maps·localization_guides·covers·chat_messages)만 write.
- `glossary`는 현재 별도 HTTP CRUD 엔드포인트가 없다. MODEL 서버는 번역 시 `workId`+목표 국가로 승인 용어집을 hydrate해서 `workMemory.approvedGlossary`로 쓰는 **읽기 경계**만 공개 계약에 포함한다. 용어집 저장/수정 UI를 WEB에서 제공하려면 WEB이 DB를 직접 관리하거나, 별도 glossary API를 새 계약으로 추가해야 한다.

| 엔드포인트 | 식별자 | save 플래그 | 응답 키 | 대상 테이블 |
|---|---|---|---|---|
| translate | `episodeId` | `saveTranslationResult` | `persisted` | translation_results |
| inspect-chat | `translationId` | `saveChatMessages` | `persistedChatMessages` | chat_messages |
| guide | `workId` | `saveGuide` | `persistedGuide` | localization_guides |
| cover | `workId` | `saveCover` | `persistedCover` | covers |
| relationship-map | `workId` | `saveRelationMap` | `persistedRelationMap` | relation_maps |
| character-extract | `workId` | (workId만으로 적재) | (응답 내) | characters |

---

## GET /health

부팅/헬스체크용. 외부 의존(Qdrant/KURE) 없이 항상 200.

**응답 200**
```json
{
  "ok": true,
  "app": "webnovel-model-server",
  "mockMode": false,
  "qdrant": "url",
  "warm": { "translation": true }
}
```
- `mockMode`: `WLIGHTER_MOCK_MODE` 반영. `qdrant`: `"url"`(서버모드) 또는 `"embedded(...)"`. `warm`: warm-up 적재 여부.

---

## POST /api/v1/translation/translate

한국어 웹소설 원문 → 목표 로케일 번역 + 문화 각주(readerEndnotes) + 리뷰 카드.

**요청** (`sourceText` 필수, `targetLocale`/`targetCountry` 중 하나 이상)

| 필드 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| `sourceText` | string | ✅ | — | 번역할 한국어 원문(min 1자) |
| `targetLocale` | string | △ | null | 예: `ko_en_us`, `ko_ja` |
| `targetCountry` | string | △ | null | 예: `US`, `JP`, `CN`, `TH` |
| `sourceLocale` | string | | `"ko"` | 원문 로케일 |
| `genre` | string | | null | 장르 힌트 |
| `workId` | string | | null | 작품 식별자 |
| `episodeId` | string | | null | 회차 식별자 |
| `workMemory` | object | | null | 승인 용어집 등 작품 메모리(dict) |
| `includeInternal` | bool | | `false` | true면 응답에 `internal` 디버그 블록 포함 |
| `saveTranslationResult` | bool | | `true` | **기본 저장**(번역 완료 시 선제 적재). 실제 저장엔 `episodeId` 필요(없으면 graceful no-op) + rdb 백엔드. summary/glossary_can/annotation_can/inspection_report까지 함께 저장 |

△ = `targetLocale`·`targetCountry` 중 최소 하나. 서비스가 normalize(둘 다 없으면 `400`).

**응답 200** (보장 키)

| 필드 | 타입 | 설명 |
|---|---|---|
| `country` / `locale` | string | 정규화된 목표 |
| `pipeline` | string\|null | 사용 파이프라인 |
| `finalTranslation` | string | 최종 번역문 (항상 deliver — 차단 상태 없음) |
| `readerEndnotes` | array<object> | 독자용 문화 각주(없으면 `[]`). 각 항목 = `{keyword, targetKeyword, koreanNote, targetNote, targetSentence, applied}` — 한국 문화 키워드 / 대상언어 키워드(A, 본문 표면형) / 한국어 미주 / 대상언어 미주 / A가 든 번역문 문장(best-effort, 못 찾으면 `""`) / `applied`(0=미적용 기본, 웹 컨펌 시 1). 웹 표시 = `targetKeyword: targetNote`. **말미 목록 스타일**(인라인 앵커링/스팬 없음 — `targetSentence`는 미주↔문장 매칭용이며 verbatim은 best-effort). `translationReport.readerEndnotes`도 동일 형태 |
| `translationReport` | object | **웹 번역 리포트 4요소** `{summary, glossaryCandidates, readerEndnotes, inspectionReport}`. DB 컬럼 `summary/glossary_can/annotation_can/inspection_report`와 1:1. 각 요소 상세·실제 JSON은 **아래 "번역 리포트 4요소" 절** 참조. |
| `authorReviewCards` | array<object> | 작가 리뷰 카드(말투/자연스러움/문화) |
| `metadata` | object | 빌드/모델 메타 |
| `internal` | object\|null | `includeInternal=true`일 때만 |
| `persisted` | object | `saveTranslationResult` 저장 시도 시에만(`{saved, translation_id}`) — DB 영속화 공통 참조 |

요청에 `saveTranslationResult`(bool, **기본 true**) + `episodeId`가 있으면 `translation_results`에 저장(번역문 + summary·glossary_can·annotation_can·inspection_report)하고 `persisted`로 결과(특히 `translation_id`)를 반환한다. 이 `translation_id`를 inspect-chat의 `translationId`로 넘기면 챗 로그가 연결된다.

**에러**: `422`(`sourceText` 누락/빈 값·타입 불일치 — Pydantic 검증), `400`(`targetLocale`·`targetCountry` 둘 다 없음 또는 로케일 정규화 실패 — 서비스 검증), `503`(엔진 미준비).

#### 번역 리포트 4요소 (translationReport) — 상세

화면설계서의 번역 리포트 화면을 구성하는 4요소다. DB `translation_results`의 4개 컬럼과 1:1.

| 요소(응답 키) | DB 컬럼 | 타입 | 의미 |
|---|---|---|---|
| `summary` | `summary` | string(text) | 5단 총평: **번역가 overview**(첫 번역가 실데이터) + 말투/자연스러움/문화권 **검수자 총평** + **최종 수정 총평**(리바이저). `\n`으로 묶인 단일 텍스트 |
| `glossaryCandidates` | `glossary_can` | array<object> | 신규 용어 후보. 항목 `{source, suggested_target, category, reason, applied}`. `applied`=0 기본(웹 컨펌 시 1) |
| `readerEndnotes` | `annotation_can` | array<object> | 독자용 문화 각주(말미 목록). 항목 `{keyword, targetKeyword, koreanNote, targetNote, targetSentence, applied}`. 표시=`targetKeyword: targetNote`, `targetSentence`=A가 든 번역문 문장(best-effort, 없으면 `""`) |
| `inspectionReport` | `inspection_report` | array<object> | **리바이저 전체 적용/보류 결정**(voice·naturalness·cultural·glossary). 항목 `{reviewerType, sourceSpan, targetSpan, problem, action, reason, revisedSpan}`. **웹은 `reviewerType=='cultural'`만 필터해 "문화리스크"로 표시**, 챗봇 핸드오프는 전체 소비. `action` ∈ {`applied`,`deferred`}(glossary는 항상 applied), `revisedSpan`은 보류 시 빈 문자열 |

> ⚠️ `inspectionReport` 변경(2026-06-24): 이전 `culturalRiskResult`(cultural만)에서 **전체 decisions로 확장 + 키명 변경**. 웹의 "문화리스크" 표시는 이제 **웹이 cultural을 필터**해야 함(이전엔 서버가 pre-filter). 옛 DB row의 `inspection_report`는 cultural-only 리스트라 읽을 때 모양 방어 권장.

> ⚠️ `readerEndnotes` 변경(2026-06-26): `targetKeyword`(A=본문 표면형)·`targetSentence`(A가 든 번역문 문장, best-effort·없으면 `""`) **2필드 추가**. 미주 작성이 **최종 번역문 확정 뒤**로 이동해 A를 본문 표면형과 일치시킴(`targetKeyword: targetNote` 표시·미주↔문장 매칭 용도). 옛 `annotation_can` row엔 두 필드가 없을 수 있으니 읽을 때 모양 방어 권장.

**실제 응답 예시** (`translationReport`):
```json
{
  "translationReport": {
    "summary": "번역가: 원문의 사건 진행과 감정선을 유지하며 일본어 독자에게 자연스럽게 읽히도록 했습니다.\n\n말투 검수자 : 캐릭터 말투 일관됨.\n자연스러움 검수자 : 직역투 1건 보정 권장.\n문화권 리스크 검수자 : '삼복더위' 배경 설명 권장.\n\n최종 수정 : 말투 1건 반영, 직역투 1건 반영, 문화 1건 보류(각주 대체).",
    "glossaryCandidates": [
      {
        "source": "철수",
        "suggested_target": "チョルス",
        "category": "person",
        "reason": "주요 등장인물 고유명사 음역.",
        "applied": 0
      }
    ],
    "readerEndnotes": [
      {
        "keyword": "삼복더위",
        "targetKeyword": "三伏の暑さ",
        "koreanNote": "한여름 가장 더운 삼복 기간의 더위를 가리키는 한국 표현.",
        "targetNote": "韓国で真夏の最も暑い「三伏」の時期の暑さを指す表現。",
        "targetSentence": "彼は三伏の暑さの中、塾へ向かった。",
        "applied": 0
      }
    ],
    "inspectionReport": [
      {
        "reviewerType": "voice",
        "sourceSpan": "철수가 말했다",
        "targetSpan": "チョルスが申しました",
        "problem": "캐릭터 말투가 장면보다 과하게 정중함.",
        "action": "applied",
        "reason": "장면상 평어가 적절.",
        "revisedSpan": "チョルスが言った"
      },
      {
        "reviewerType": "naturalness",
        "sourceSpan": "비가 억수같이 쏟아졌다",
        "targetSpan": "雨が水のように降った",
        "problem": "직역투로 어색함.",
        "action": "applied",
        "reason": "관용 표현으로 자연화.",
        "revisedSpan": "雨が土砂降りになった"
      },
      {
        "reviewerType": "cultural",
        "sourceSpan": "삼계탕",
        "targetSpan": "サムゲタン",
        "problem": "현지 독자에게 문화 배경 설명이 필요.",
        "action": "deferred",
        "reason": "본문 수정 대신 독자 각주로 대체.",
        "revisedSpan": ""
      },
      {
        "reviewerType": "glossary",
        "sourceSpan": "철수",
        "targetSpan": "チョルス",
        "problem": "승인 용어집 표기 일관성.",
        "action": "applied",
        "reason": "승인 표기 강제(glossary는 항상 반영).",
        "revisedSpan": "チョルス"
      }
    ]
  }
}
```
위에서 웹 "문화리스크" 화면 = `inspectionReport.filter(d => d.reviewerType === 'cultural')`.

---

### Translation WorkMemory / Glossary hydrate

번역 품질 고정을 위한 승인 용어집은 `workMemory.approvedGlossary`로 엔진에 전달된다. 현재 공개 HTTP 계약은 **저장 API가 아니라 사용/주입 계약**이다.

**사용 방식**

1. 요청에 `workMemory`를 직접 넣으면 그 값이 최우선이다.
2. `workMemory`가 없고 `workId` + `targetCountry`/`targetLocale`이 있으면 MODEL 서버가 내부 glossary repository에서 승인 용어집을 조회해 `workMemory`를 hydrate한다.
3. repository backend는 `GLOSSARY_STORE_BACKEND` 설정을 따른다. `mysql`이면 MySQL `glossary` 테이블을 조회하고, 미설정/장애 시 memory repo로 graceful fallback한다.

**저장 모델(내부 repository 기준)**

| 필드 | 설명 |
|---|---|
| `glossary_id` | 용어집 행 ID |
| `work_id` | 작품 ID. MySQL backend에서는 숫자형 `works.work_id` |
| `target_country` | `JP`/`US`/`CN`/`TH` 등 2자리 국가 코드 |
| `original_word` | 원문 용어. 대명사/지시어성 표현은 저장 거부 |
| `translated_word` | 승인 번역어 |
| `glossary_type` | `person`/`place`/`organization` |
| `memo` | 선택 메모 |

**현재 없는 것**

- `POST /api/v1/glossary`, `GET /api/v1/glossary`, `DELETE /api/v1/glossary/{id}` 같은 공개 CRUD 엔드포인트는 아직 없다.
- `captureGlossaryCandidates=true`는 graph 내부 hook이 있을 때만 후보 캡처를 호출하는 확장 지점이며, hook 미설치 상태에서는 `reason=no_capture_hook`으로 저장하지 않는다.

즉 WEB(Django)이 “용어집 저장/수정 화면”을 가져가려면 현재 계약만으로는 부족하다. 선택지는 (A) WEB이 `glossary` 테이블을 직접 관리하고 MODEL은 hydrate-only로 유지하거나, (B) MODEL에 별도 glossary CRUD API를 추가해 이 문서에 신규 엔드포인트로 고정하는 방식이다.

---

## POST /api/v1/translation/inspect-chat

번역 검수 챗봇 — 질문 답변 + 선택적 번역 수정 제안(`edits`, 프론트 버튼 적용) + glossary DB 편집(사용자 확인 후).

**요청** (`question` 필수)

| 필드 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| `question` | string | ✅ | — | 질문(min 1자) |
| `sourceText` | string | | `""` | 원문 컨텍스트 |
| `currentTranslation` | string | | `""` | 현재 번역문 |
| `targetLocale` / `targetCountry` | string | | null | 목표 |
| `workflow` | object | | null | 워크플로 상태 |
| `chatHistory` | array<object> | | null | 이전 대화 |
| `title` / `episodeId` | string | | null | 작품/회차 |
| `workId` | string | | null | glossary 수정 시 필요. 없으면 glossary 편집 액션은 graceful 실패 |
| `translationId` | int | | null | 주면 검수 대화를 `chat_messages`에 저장(rdb일 때) + DB에서 `inspectionReport` 자동 로드 |
| `saveChatMessages` | bool | | `true` | `translationId`가 있을 때 저장 여부 |
| `pendingAction` | object\|null | | null | 이전 턴 응답의 `pendingAction`을 그대로 전달. 사용자 확인/취소 메시지 전송 시 세팅 |

**응답 200**

| 필드 | 타입 | 설명 |
|---|---|---|
| `answer` | string | 챗봇 답변 |
| `edits` | array<object>\|null | 번역 수정 제안. 각 원소 `{original, replacement}` — 프론트가 번역본에서 `original`을 정확 문자열 매칭으로 찾아 `replacement`로 교체(적용 버튼). 수정 없으면 `[]` |
| `changeSummary` | string\|null | 변경 요약 |
| `needsUserConfirmation` | bool | 사용자 확인 필요 여부 |
| `pendingAction` | object\|null | 챗봇이 제안하는 DB 액션. 다음 요청 시 그대로 `pendingAction` 필드에 실어 전송. null이면 대기 액션 없음 |
| `actionExecuted` | object\|null | 이번 턴에 실행된 액션 결과 `{type, saved, ...}`. DB 변경이 실제로 일어난 경우에만 존재 |
| `persistedChatMessages` | object | `translationId` 저장 시도 시에만(`{saved, count, message_ids}`) |

**pendingAction 객체 형식**

```json
{
  "type": "update_glossary",
  "description": "민제(minje)를 minjea로 변경",
  "original_word": "민제",
  "new_value": "minjea",
  "category": "person"
}
```

| `type` | 동작 | 필요 필드 |
|---|---|---|
| `update_glossary` | 기존 glossary 항목 번역어 수정 | `original_word`, `new_value`, `category` + 요청의 `workId` |
| `add_glossary` | glossary 신규 추가 | `original_word`, `new_value`, `category` + 요청의 `workId` |
| `delete_glossary` | glossary 항목 삭제 | `original_word` + 요청의 `workId` |

> 번역문 수정은 `pendingAction`이 아니라 응답의 `edits`로 내려가며, **프론트 '번역 제안 적용' 버튼**이 처리한다(서버가 번역본 DB를 직접 쓰지 않음). `pendingAction`은 glossary(용어집) 편집 전용이다.

**pendingAction 플로우 (프론트 구현 규약)**

```
[Turn N]
  요청:  { question: "민제를 minjea로 바꿔줘", workId: "123", ... }
  응답:  { answer: "바꿀까요?", pendingAction: { type: "update_glossary", ... }, needsUserConfirmation: true }

[Turn N+1]
  요청:  { question: "응 바꿔줘", workId: "123", pendingAction: { type: "update_glossary", ... }, ... }
  응답:  { answer: "변경했습니다.", actionExecuted: { type: "update_glossary", saved: true }, pendingAction: null }
```

- 응답 `pendingAction`이 non-null → 프론트가 로컬 저장 후 **다음 요청에 그대로** 포함
- 응답 `pendingAction`이 null → 저장된 값 초기화
- 확인/취소 판정은 서버가 키워드 기반으로 처리 ("네/응/해줘" → confirm, "아니/취소/됐어" → cancel)

---

## POST /api/v1/guide  ·  GET /api/v1/guide/_status

작품 정보 → 현지화 가이드(시장 트렌드·컨텍스트팩·정책 유의사항). 공개 응답은 relationship-map처럼 프론트 표시용 HTML 중심으로 반환한다.
시놉시스가 있으면 작품 분석과 국가별 적합도를 비교하는 **국가 추천 리포트**를 반환한다.
시놉시스가 없으면 `targetCountry`/`genre`/관심 입력을 기준으로 국가·장르 일반 가이드를 생성한다.
가이드는 작품의 플롯·결말·캐릭터·핵심 설정을 바꾸는 창작 컨설팅이 아니라, 작품을 현재 방향 그대로 두고 제목·소개문·태그·표지 브리프·정책 검토·독자 기대치 전달 방식을 정리하는 현지화 리포트다.

**요청** (모두 선택, 엔진이 추가 키도 직접 사용 → `extra=allow`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `title` / `genre` / `synopsis` | string | 작품 정보 |
| `targetCountry` | string | `japan/english/china/thailand` 또는 `JP/US/CN/TH` |
| `targetMarket` | string | 시장 |
| `titleElements` | array<string> | 제목 요소 |
| `comparableSignals` | array<string> | 비교작 신호 |
| `includeContextPack` | bool | 컨텍스트 참고자료 사용 토글 |
| `includeLiveMarket` | bool | Tavily 실시간 웹 근거 사용 여부. 기본은 서버 환경변수 `WLIGHTER_GUIDE_TAVILY`를 따른다 |
| `workId` | int | 주면 작품 정보 보강 + 가이드 결과를 `localization_guides`에 저장(rdb일 때) |
| `saveGuide` | bool | `workId`가 있을 때 저장 여부(기본 `true`) |

**응답 200**: 항상 `htmlReport`(완성형 HTML) + 최소 표시/상태 메타를 반환한다. 국가 추천 모드에는 `countryComparisons`, `availableCountries`, `recommendedCountry`, `recommendedCountryDisplay`, `confidence`, `limitations`가 추가되며, 공개 응답의 필드명은 camelCase만 사용한다.
`htmlReport`는 relationship-map과 동일하게 `<!doctype html>` + `<head><style>...</style></head>` + `<body>`를 포함한 **CSS 내장 완성형 HTML 문서**다. WEB(Django)은 도메인별 CSS를 따로 주입하지 않고, 공통적으로 iframe `srcdoc` 방식 렌더링을 권장한다.
`contextPackEvidence`, `contextPackBriefing`, `modelPromptPayload`, `evidenceUsed`, `qualitySummary`, `actionChecklist`, raw LLM error 등 내부 판단/디버그 필드는 공개 응답에 포함하지 않는다.
`reportMode`는 `synopsis_country_recommendation`(시놉시스 기반 국가 추천)과 `country_genre_guide`(국가+장르 일반 리포트)를 사용한다.

`synopsis_country_recommendation`은 완결된 국가 비교 리포트이며 `requiresSelection=false`로 반환하고 저장하지 않는다.
`generationMode`는 생성 경로만 나타내며 `recommendation_only`, `deterministic_guide`, `llm_with_rag` 중 하나다.
`workId` 저장 시 `persistedGuide`(`{saved, guide_id}`) 추가 — DB 영속화 공통 참조.

**`GET /_status` 200**: 도메인 상태(서비스 준비 여부 등).

**에러**: `400`(검증 실패), `503`(데이터/LLM 미준비).

---

## POST /api/v1/cover  ·  GET /api/v1/cover/_status

작품·캐릭터 정보 → 표지 이미지(base64). `dryRun=true`면 최종 프롬프트만.

**요청**

| 필드 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `workTitle` | string | `""` | 작품명 |
| `genre` | string | `""` | 장르 |
| `synopsis` | string | `""` | 시놉시스 |
| `characters` | array<object> | `[]` | 캐릭터 설정집 |
| `targetCountry` | string | `"KR"` | `KR/US/CN/JP/TH` |
| `userPrompt` | string | `""` | 추가 요청(최대 500자) |
| `dryRun` | bool | `false` | true면 이미지 생성 없이 최종 프롬프트만 |
| `workId` | int | null | 주면 표지 URL을 `covers`에 저장(rdb일 때) |
| `coverUrl` | string | null | 이미 저장된 표지 URL/S3 경로가 있으면 `covers.cover_url`에 저장 |
| `mainCoverYn` | bool | `false` | 대표 표지 여부 |
| `saveCover` | bool | `true` | `workId`가 있을 때 저장 여부 |

**응답 200**: `status`(string) + 엔진 출력(`final_prompt`, `image_base64` 등). `dryRun=false`면 실 이미지 base64.
`workId` 저장 시 `persistedCover`(`{saved, cover_id, cover_url}`) 추가. S3 설정(`AWS_S3_BUCKET_NAME`)이 있으면 생성 이미지를 S3에 업로드하고 `coverUrl`, `imageUrl`, `presignedCoverUrl`, `s3Key`, `s3Uri`를 반환한다. S3 설정이 없으면 기존처럼 `/generated/...` 로컬 경로를 사용한다 — DB 영속화 공통 참조.

**에러**: `400`(프롬프트 검증), `503`(OpenAI 키 미설정 등).

---

## POST /api/v1/relationship-map  ·  GET /api/v1/relationship-map/_status

캐릭터 설정집 → 인물 관계도 데이터(+옵션 HTML).

**요청**

| 필드 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `workTitle` | string | `""` | 작품명 |
| `characters` | array<object> | `[]` | 캐릭터 설정집 |
| `limit` | int | `12` | 관계도 캐릭터 수(1~20) |
| `includeHtml` | bool | `true` | true면 관계도 HTML도 반환 |
| `workId` | int | null | 주면 DB 작품/캐릭터를 조회하고 관계도를 `relation_maps`에 저장(rdb일 때) |
| `saveRelationMap` | bool | `true` | `workId`가 있을 때 저장 여부 |

**응답 200**: `data`(characters/relations/groups) + `htmlReport`(includeHtml=true). `htmlReport`는 `<!doctype html>` + `<style>`을 포함한 CSS 내장 완성형 HTML 문서다. `extra=allow`.
`workId` 저장 시 `persistedRelationMap`(`{saved, map_id}`) 추가 — DB 영속화 공통 참조.
> `workId`만 주고 `characters`를 비우면 DB에 저장된 캐릭터를 조회해 관계도를 만든다.

**에러**: `400`(빈 캐릭터/limit 범위), `503`(엔진 도달, 키 필요).

---

## POST /api/v1/character-extract  ·  GET /api/v1/character-extract/_status

시놉시스 → 등장인물 목록(이름·역할·외형·관계 등).

**요청** (`synopsis` 필수)

| 필드 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| `workTitle` | string | | `""` | 작품명 |
| `genre` | string | | `""` | 장르 |
| `synopsis` | string | ✅ | — | 등장인물 추출 대상(min 1자) |
| `limit` | int | | `20` | 추출 인물 수(1~30) |
| `workId` | int | | null | 주면 결과를 해당 작품 `CHARACTERS`에 적재(rdb 백엔드일 때) |

**응답 200**

| 필드 | 타입 | 설명 |
|---|---|---|
| `work_title` | string\|null | 작품명 |
| `genre` | string\|null | 장르 |
| `count` | int\|null | 추출 인물 수 |
| `characters` | array<object> | 인물 목록(이름·역할·외형·관계 등) |

**에러**: `422`(빈 시놉시스/limit 범위 등 스키마 검증), `503`(OpenAI 키 미설정 등).

---

## 엔드포인트 요약

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| POST | `/api/v1/translation/translate` | 번역 + 문화 각주 + 리뷰 카드 |
| POST | `/api/v1/translation/inspect-chat` | 번역 검수 챗봇 |
| POST | `/api/v1/guide` | 현지화 가이드 |
| POST | `/api/v1/cover` | 표지 이미지(base64) |
| POST | `/api/v1/relationship-map` | 인물 관계도 |
| POST | `/api/v1/character-extract` | 등장인물 추출 |
| GET | `/api/v1/{guide,cover,relationship-map,character-extract}/_status` | 도메인 상태 |

> 모든 응답은 `extra=allow` — 표의 키는 **보장 최소 집합**이고, 실제 응답엔 엔진이 키를 더 실을 수 있다.
> 정확한 실시간 스키마는 `GET /docs`(Swagger) / `GET /openapi.json` 참조.
