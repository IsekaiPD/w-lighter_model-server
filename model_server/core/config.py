"""앱 설정 — pydantic-settings로 .env / 환경변수 로드.

엔진(translation 등)은 내부적으로 os.getenv(WLIGHTER_MOCK_MODE, OPENAI_API_KEY 등)를
직접 읽으므로, 여기서 load_dotenv()로 .env를 os.environ에 먼저 주입한 뒤 타입드 접근을 제공한다.
"""
from __future__ import annotations

from functools import lru_cache

try:  # .env를 os.environ에 주입(엔진의 os.getenv 호환). 미설치여도 동작.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # --- 앱 ---
    app_name: str = "webnovel-model-server"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]

    # --- 모델/키 (엔진이 os.getenv로도 읽음) ---
    openai_api_key: str = ""        # OPENAI_API_KEY
    hf_token: str = ""              # HF_TOKEN (KURE 다운로드)
    wlighter_mock_mode: bool = False  # WLIGHTER_MOCK_MODE — true면 외부 호출 없이 결정적

    # --- Qdrant (self-host 별도 컨테이너) ---
    # 비어 있으면 엔진이 임베디드 path= 폴백(현재). TODO: 엔진 make_qdrant_client를 url= 전환.
    qdrant_url: str = ""            # QDRANT_URL e.g. http://qdrant:6333

    # --- 저장소 백엔드 ---
    # memory: 프로세스 메모리(휘발). rdb: SQLAlchemy(database_url; 비면 로컬 SQLite 파일).
    # 기본은 memory 유지(부팅 빠름·테스트 결정적). 로컬 영속화 테스트/배포는 rdb로 전환.
    glossary_store_backend: str = "memory"   # memory | rdb | mysql
    content_store_backend: str = "memory"    # memory | rdb
    # SQLAlchemy 연결 URL. 비면 rdb일 때 로컬 SQLite 파일(model_server/wlighter_local.db)로 폴백.
    # MySQL 전환은 이 한 줄만: mysql+pymysql://user:pw@host:3306/dbname?charset=utf8mb4
    database_url: str = ""                    # DATABASE_URL
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = ""
    mysql_user: str = ""
    mysql_password: str = ""

    # --- 기동 동작 ---
    # 무거운 파이프라인(KURE/qdrant) startup warm-up 여부. 기본 off(스캐폴드/구성도 단계는 빠른 부팅).
    warmup_on_startup: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
