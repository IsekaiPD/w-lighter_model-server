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
| `finalTranslation` | string | 최종 번역문 |
| `deliveryStatus` | string | 예: `deliverable` |
| `userVisibleErrorCode` | string\|null | 사용자 표시용 에러코드 |
| `message` | string | 보조 메시지 |
| `translationRationale` | object | 번역 근거(중첩). 리포트 4요소 아님 — `inspect-chat` 검수 챗봇 컨텍스트로 넘기는 용도(웹이 보관 후 전달) |
| `readerEndnotes` | array<object> | 독자용 문화 각주(없으면 `[]`). 각 항목 = `{keyword, koreanNote, targetNote, applied}` — 한국 문화 키워드 / 한국어 미주 / 대상언어 미주 / `applied`(0=미적용 기본, 웹 컨펌 시 1). **말미 목록 스타일**(번역문 위치 앵커링 없음, 스팬 필드 없음). `translationReport.readerEndnotes`도 동일 형태 |
| `translationReport` | object | **웹 번역 리포트 4요소**. `{summary, glossaryCandidates, readerEndnotes, culturalRiskResult}` — `summary`(text, 5단: 번역가 overview + 말투/자연스러움/문화권 검수자 총평 + 최종수정 총평), `glossaryCandidates`(각 항목 `{source, suggested_target, category, reason, applied(0/1)}`), `readerEndnotes`(각 항목 `{keyword, koreanNote, targetNote, applied(0/1)}`), `culturalRiskResult`(문화리스크 = 리바이저 cultural 적용/보류 결정 `{reviewerType, problem, action(applied/deferred), reason, revisedSpan, ...}`). DB 컬럼 `summary/glossary_can/annotation_can/inspection_report`와 1:1. (`translationRationale`은 리포트가 아니라 **top-level**에 별도 — 검수 챗봇 컨텍스트용) |
| `authorReviewCards` | array<object> | 작가 리뷰 카드(말투/자연스러움/문화) |
| `qaIssues` | array<object> | QA 이슈 |
| `metadata` | object | 빌드/모델 메타 |
| `internal` | object\|null | `includeInternal=true`일 때만 |
| `persisted` | object | `saveTranslationResult` 저장 시도 시에만(`{saved, translation_id}`) — DB 영속화 공통 참조 |

요청에 `saveTranslationResult`(bool, **기본 true**) + `episodeId`가 있으면 `translation_results`에 저장(번역문 + summary·glossary_can·annotation_can·inspection_report)하고 `persisted`로 결과(특히 `translation_id`)를 반환한다. 이 `translation_id`를 inspect-chat의 `translationId`로 넘기면 챗 로그가 연결된다.

**에러**: `422`(`sourceText` 누락/빈 값·타입 불일치 — Pydantic 검증), `400`(`targetLocale`·`targetCountry` 둘 다 없음 또는 로케일 정규화 실패 — 서비스 검증), `503`(엔진 미준비).

---

## POST /api/v1/translation/inspect-chat

번역 검수 챗봇 — 질문에 대한 답변(+선택적 수정 제안).

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
| `translationId` | int | | null | 주면 검수 대화를 `chat_messages`에 저장(rdb일 때) |
| `saveChatMessages` | bool | | `true` | `translationId`가 있을 때 저장 여부 |

**응답 200**

| 필드 | 타입 | 설명 |
|---|---|---|
| `answer` | string | 챗봇 답변 |
| `proposedTranslation` | string\|null | 수정 제안(있으면) |
| `changeSummary` | string\|null | 변경 요약 |
| `needsUserConfirmation` | bool | 사용자 확인 필요 여부 |
| `persistedChatMessages` | object | `translationId` 저장 시도 시에만(`{saved, count, message_ids}`) — DB 영속화 공통 참조 |

---

## POST /api/v1/guide  ·  GET /api/v1/guide/_status

작품 정보 → 현지화 가이드(시장 트렌드·컨텍스트팩·정책 유의사항). 공개 응답은 relationship-map처럼 프론트 표시용 HTML 중심으로 반환한다.

**요청** (모두 선택, 엔진이 추가 키도 직접 사용 → `extra=allow`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `title` / `genre` / `synopsis` | string | 작품 정보 |
| `targetCountry` | string | `japan/english/china/thailand` 또는 `JP/US/CN/TH` |
| `targetMarket` | string | 시장 |
| `titleElements` | array<string> | 제목 요소 |
| `comparableSignals` | array<string> | 비교작 신호 |
| `legacyGuide` / `includeContextPack` | bool | 토글 |
| `workId` | int | 주면 작품 정보 보강 + 가이드 결과를 `localization_guides`에 저장(rdb일 때) |
| `saveGuide` | bool | `workId`가 있을 때 저장 여부(기본 `true`) |

**응답 200**: `htmlReport`(완성형 HTML) + 최소 표시/상태 메타(`mode`, `generationMode`, `requiresSelection`, `title`, `targetCountry`, `targetCountryDisplay`, `displayCountry`, `country`, `llmGeneratedGuide`, `message` 등).
`htmlReport`는 relationship-map과 동일하게 `<!doctype html>` + `<head><style>...</style></head>` + `<body>`를 포함한 **CSS 내장 완성형 HTML 문서**다. WEB(Django)은 도메인별 CSS를 따로 주입하지 않고, 공통적으로 iframe `srcdoc` 방식 렌더링을 권장한다.
`contextPackEvidence`, `contextPackBriefing`, `modelPromptPayload`, `evidenceUsed`, `qualitySummary`, `actionChecklist`, raw LLM error 등 내부 판단/디버그 필드는 공개 응답에 포함하지 않는다.
국가 선택이 필요한 recommendation-only 응답은 `requiresSelection=true`와 추천/선택에 필요한 최소 필드만 반환한다.
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
