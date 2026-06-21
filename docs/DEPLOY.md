# DEPLOY — w-lighter MODEL 서버 (FastAPI + Qdrant)

FastAPI(`app`)와 Qdrant를 **하나의 `docker-compose.yml`**로 각각 별도 컨테이너로 띄우고,
compose 내부 네트워크로 연결한다(서비스명 = DNS 호스트명 → app은 `http://qdrant:6333`로 접근).

## 구조

```
[외부 사용자] → :8000 → app (FastAPI)  ──내부망 http://qdrant:6333──→  qdrant (벡터 DB)
                          │                                              └ volume: qdrant_data (영속)
                          └ hf_cache volume(KURE 캐시), env_file: model_server/.env
```

- qdrant 포트는 **외부 미공개**(compose 내부망 전용). app 컨테이너만 접근, 호스트·외부 차단.
- 시크릿은 이미지에 굽지 않고 런타임 주입(`env_file=model_server/.env`, gitignore). 계약 SoT는 `.env.example`.

## 사전 준비

1. `cp .env.example model_server/.env` 후 값 채우기:
   - `OPENAI_API_KEY`(필수, 실키), `HF_TOKEN`(KURE — 공개모델이면 비워도 됨)
   - `QDRANT_URL=http://qdrant:6333`(컨테이너 내부 DNS), `WLIGHTER_MOCK_MODE=false`
   - 인라인 주석 금지(`KEY=값 # ...` → docker env_file이 주석을 값으로 먹음). 주석은 키 윗줄에.

## 실행 순서

```bash
# 1) 이미지 빌드
docker compose build

# 2) qdrant 먼저 기동
docker compose up -d qdrant

# 3) 벡터 컬렉션 시드 (호스트 아닌 컨테이너 안에서 — 일회성 컨테이너)
#    kculture = 라이브 문화 각주(readerEndnotes)용. JSON에서 KURE로 재임베딩 → qdrant 적재.
docker compose run --rm app python scripts/seed_kculture_from_json.py

# 4) app 기동 (warm-up이 KURE를 hf_cache 볼륨에서 로드)
docker compose up -d app

# 5) 검증
curl http://localhost:8000/health
#   → mock=false로 POST /api/v1/translation/translate 시 readerEndnotes 산출
```

> 주의: app 컨테이너 안에서 `127.0.0.1:6333`을 쓰면 qdrant가 아니라 자기 자신을 가리킨다.
> 반드시 `http://qdrant:6333`(=`QDRANT_URL`)을 사용한다.

## 프로덕션 env override (배포 시 명시)

| env | 값 | 이유 |
|---|---|---|
| `WARMUP_ON_STARTUP` | `1` (compose에 이미 ON) | 첫 요청 콜드스타트 방지(KURE 사전 적재) |
| `CONTENT_STORE_BACKEND` | `rdb` (코드 기본값 — 안 B) | DB 영속화 활성. 비우면 자동 rdb. (테스트만 `memory` 명시) |
| `DATABASE_URL` | `mysql+pymysql://…` | **prod 필수**: 비우면 rdb가 컨테이너 SQLite로 폴백(데이터 갇힘). 전환은 이 한 줄만(코드 불변) |
| `WLIGHTER_ANNOTATION_SCORE_THRESHOLD` | `0.55`(기본) | 문화 각주 검색 임계치(↑보수적 / ↓적극적) |
| CORS origin | 좁히기 | 현재 `*` |

## 데이터/캐시 영속성

- `qdrant_data` 볼륨: 시드한 컬렉션 보존(컨테이너 내려도 유지). 새 서버는 위 3) 시드를 1회 실행.
- `hf_cache` 볼륨: KURE 모델 캐시(재다운로드 방지). 첫 기동만 다운로드(~2GB), 이후 캐시 로드(~2s).

## 참고

- 컬렉션 범위: 현재 **kculture만** 시드(라이브 각주에 쓰임). idiom_jp/us/cn/th는 v3 파이프라인 미배선이라 미시드.
- 로컬에서 qdrant를 호스트에서 직접 보려면 `docker-compose.yml`의 qdrant `ports:` 주석을 한시적으로 해제.
