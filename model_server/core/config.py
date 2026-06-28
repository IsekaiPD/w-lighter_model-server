"""앱 설정 — pydantic-settings로 .env / 환경변수 로드.

엔진이 os.getenv로 직접 읽으므로 load_dotenv()로 .env를 os.environ에 주입한 뒤 타입드 접근을 제공한다.
"""

from __future__ import annotations

from functools import lru_cache

try:  # .env를 os.environ에 주입. dotenv 미설치여도 동작.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- 앱 ---
    app_name: str = "webnovel-model-server"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]
    max_request_body_bytes: int = 512 * 1024  # MAX_REQUEST_BODY_BYTES
    rate_limit_enabled: bool = True  # RATE_LIMIT_ENABLED

    # --- 모델/키 (엔진이 os.getenv로도 읽음) ---
    openai_api_key: str = ""  # OPENAI_API_KEY
    hf_token: str = ""  # HF_TOKEN (KURE 다운로드)
    wlighter_mock_mode: bool = (
        False  # WLIGHTER_MOCK_MODE — true면 외부 호출 없이 결정적
    )

    # --- Qdrant (self-host 별도 컨테이너) ---
    # 비어 있으면 엔진이 임베디드 path= 폴백. TODO: 엔진 make_qdrant_client를 url= 전환.
    qdrant_url: str = ""  # QDRANT_URL e.g. http://qdrant:6333

    # --- 저장소 백엔드 ---
    # memory: 프로세스 메모리(휘발). rdb: SQLAlchemy(database_url; 비면 로컬 SQLite 파일).
    # 기본 rdb (안 B, 2026-06-21 결정): 실서비스 가정에서 "깜빡 memory→prod 데이터 증발" footgun 제거.
    #   로컬은 DATABASE_URL 비우면 SQLite 파일로 폴백(서버 불요). 테스트/CI는 CONTENT_STORE_BACKEND=memory 명시.
    # [DEPRECATED·무시됨] glossary 백엔드는 더 이상 이 토글로 고르지 않는다. _glossary_repository가
    #   DATABASE_URL/MYSQL_* 접속 가능하면 MySQL, 아니면 in-memory로 **자동 결정**한다
    #   (옛 .env의 GLOSSARY_STORE_BACKEND=memory 가 dedup을 깨던 footgun 제거). 필드는 구 .env 호환용으로만 남김.
    glossary_store_backend: str = "mysql"  # (deprecated) 값 사용 안 함 — DATABASE_URL 유무로 자동 결정
    content_store_backend: str = "rdb"  # memory | rdb
    # SQLAlchemy 연결 URL. 비면 rdb일 때 로컬 SQLite 파일(model_server/wlighter_local.db)로 폴백.
    # MySQL 전환 예: mysql+pymysql://user:pw@host:3306/dbname?charset=utf8mb4
    database_url: str = ""  # DATABASE_URL
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = ""
    mysql_user: str = ""
    mysql_password: str = ""

    # --- 기동 동작 ---
    # 무거운 파이프라인(KURE/qdrant) startup warm-up 여부. 기본 off(빠른 부팅).
    warmup_on_startup: bool = False

    enable_docs: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
