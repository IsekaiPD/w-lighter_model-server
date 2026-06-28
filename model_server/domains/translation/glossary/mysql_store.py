from __future__ import annotations

import importlib
import os
import urllib.parse
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Iterator

from .store import (
    DEFAULT_CATEGORY,
    GLOSSARY_CATEGORIES,
    GlossaryEntryRecord,
    GlossaryRepository,
    WorkMemory,
    _clean,
    hydrate_work_memory_from_records,
    is_contextual_reference,
    normalize_category,
)
from ..infra.locale_utils import normalize_target_country


class MySQLDriverUnavailable(RuntimeError):
    pass


def normalize_mysql_work_id(value: Any) -> int:
    """Return a numeric works.work_id for the MySQL glossary schema."""

    if value is None or value == "":
        raise ValueError("work_id is required")
    try:
        work_id = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("work_id must be a numeric works.work_id for the MySQL glossary backend") from exc
    if work_id <= 0:
        raise ValueError("work_id must be a positive numeric works.work_id for the MySQL glossary backend")
    return work_id


def _load_driver() -> tuple[str, Any]:
    """Load an installed MySQL DB-API driver, preferring PyMySQL then mysql-connector-python."""

    try:
        return "pymysql", importlib.import_module("pymysql")
    except ImportError:
        pass
    try:
        return "mysql.connector", importlib.import_module("mysql.connector")
    except ImportError as exc:
        raise MySQLDriverUnavailable(
            "No MySQL client installed. Install PyMySQL or mysql-connector-python to use MySQLGlossaryRepository."
        ) from exc


def _mysql_params_from_database_url() -> dict[str, Any] | None:
    """content store가 쓰는 DATABASE_URL을 PyMySQL 접속 파라미터로 변환.

    glossary 전용 MYSQL_* 가 비어 있을 때, 번역본 저장과 **같은 RDS/같은 DB**를 재사용하기 위함
    (glossary 테이블도 그 DB에 있음 → django가 쓴 행을 직접 읽음). mysql 계열 URL이 아니면
    (예: 로컬 SQLite 폴백) None을 반환해 상위(_glossary_repository)가 memory로 폴백하게 둔다.
    """
    try:
        from core.config import settings

        url = (settings.database_url or "").strip()
    except Exception:  # noqa: BLE001 — 설정 로드 실패는 폴백
        url = ""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme.startswith("mysql"):  # sqlite 등은 PyMySQL로 접속 불가
        return None
    database = (parsed.path or "").lstrip("/")
    if not database or not parsed.username:
        return None
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "database": database,
        "user": urllib.parse.unquote(parsed.username),
        "password": urllib.parse.unquote(parsed.password or ""),
    }


class MySQLGlossaryRepository(GlossaryRepository):
    """MySQL 8.x implementation of the single-table glossary repository.

    컬럼명은 ERD(`project_docs/ERD_planning.txt`) GLOSSARY를 정본으로 따른다.
    Expected schema (created out-of-band)::

        CREATE TABLE glossary (
          glossary_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
          work_id         BIGINT NOT NULL,            -- works.work_id
          target_country  CHAR(2) NOT NULL,           -- JP / US / CN / TH
          original_word   VARCHAR(30) NOT NULL,
          translated_word VARCHAR(30) NOT NULL,
          glossary_type   VARCHAR(15) NOT NULL,       -- person / place / organization
          memo            VARCHAR(500) NULL,
          created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_glossary (work_id, target_country, original_word, glossary_type)
        );
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        database: str | None = None,
        user: str | None = None,
        password: str | None = None,
        charset: str | None = None,
        connect_timeout: int | None = None,
    ) -> None:
        self.host = host or os.getenv("MYSQL_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("MYSQL_PORT", "3306"))
        self.database = database or os.getenv("MYSQL_DATABASE", "")
        self.user = user or os.getenv("MYSQL_USER", "")
        self.password = password if password is not None else os.getenv("MYSQL_PASSWORD", "")
        self.charset = charset or os.getenv("MYSQL_CHARSET", "utf8mb4")
        self.connect_timeout = int(connect_timeout or os.getenv("MYSQL_CONNECT_TIMEOUT", "3"))
        self._driver_name, self._driver = _load_driver()
        if not self.database or not self.user:
            raise ValueError("MYSQL_DATABASE and MYSQL_USER are required for MySQLGlossaryRepository")

    @classmethod
    def from_env(cls) -> "MySQLGlossaryRepository":
        # MYSQL_* 가 명시돼 있으면 그걸 우선(override). 없으면 content store와 동일한
        # DATABASE_URL을 재사용 → 운영에서 glossary용 env 추가 없이 같은 RDS의 glossary 테이블을 읽는다.
        if os.getenv("MYSQL_DATABASE") and os.getenv("MYSQL_USER"):
            return cls()
        params = _mysql_params_from_database_url()
        if params:
            return cls(**params)
        return cls()  # 둘 다 없음 → __init__ 필수검증 ValueError → 상위가 memory 폴백

    def ping(self) -> None:
        with self._connect() as conn, self._cursor(conn) as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self._driver_name == "pymysql":
            conn = self._driver.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                charset=self.charset,
                autocommit=False,
                cursorclass=self._driver.cursors.DictCursor,
                connect_timeout=self.connect_timeout,
            )
        else:
            conn = self._driver.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                charset=self.charset,
                autocommit=False,
                connection_timeout=self.connect_timeout,
            )
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _cursor(self, conn: Any) -> Iterator[Any]:
        if self._driver_name == "mysql.connector":
            cur = conn.cursor(dictionary=True)
        else:
            cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    @staticmethod
    def _normalize_payload(
        *,
        work_id: str,
        target_country: str,
        original_word: str,
        translated_word: str,
        glossary_type: str,
        memo: str | None = None,
    ) -> dict[str, Any]:
        normalized = {
            "work_id": normalize_mysql_work_id(work_id),
            "target_country": normalize_target_country(target_country) or "",
            "original_word": _clean(original_word)[:30],     # ERD VARCHAR(30)
            "translated_word": _clean(translated_word)[:30],  # ERD VARCHAR(30)
            "glossary_type": normalize_category(glossary_type),
            "memo": (_clean(memo)[:500] or None),             # ERD memo VARCHAR(500)
        }
        if not normalized["target_country"] or not normalized["original_word"] or not normalized["translated_word"]:
            raise ValueError("work_id, target_country, original_word, and translated_word are required")
        if is_contextual_reference(normalized["original_word"]):
            raise ValueError("original_word is a contextual reference and should not be persisted as a glossary entry")
        return normalized

    def upsert_entry(
        self,
        *,
        work_id: str,
        target_country: str,
        original_word: str,
        translated_word: str,
        glossary_type: str = DEFAULT_CATEGORY,
        memo: str | None = None,
    ) -> GlossaryEntryRecord:
        payload = self._normalize_payload(
            work_id=work_id,
            target_country=target_country,
            original_word=original_word,
            translated_word=translated_word,
            glossary_type=glossary_type,
            memo=memo,
        )
        with self._connect() as conn:
            try:
                with self._cursor(conn) as cur:
                    cur.execute(
                        """
                        SELECT glossary_id FROM glossary
                        WHERE work_id=%s AND target_country=%s AND original_word=%s AND glossary_type=%s
                        LIMIT 1
                        """,
                        (payload["work_id"], payload["target_country"], payload["original_word"], payload["glossary_type"]),
                    )
                    existing = cur.fetchone()
                    if existing:
                        entry_id = int(existing["glossary_id"])
                        cur.execute(
                            "UPDATE glossary SET translated_word=%s, memo=%s WHERE glossary_id=%s",
                            (payload["translated_word"], payload["memo"], entry_id),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO glossary (work_id, target_country, original_word, translated_word, glossary_type, memo)
                            VALUES (%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                payload["work_id"],
                                payload["target_country"],
                                payload["original_word"],
                                payload["translated_word"],
                                payload["glossary_type"],
                                payload["memo"],
                            ),
                        )
                        entry_id = int(cur.lastrowid)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        row = self.get_entry(entry_id)
        if row is None:
            raise RuntimeError(f"glossary entry {entry_id} was not found after upsert")
        return row

    def list_glossary(self, work_id: str, target_country: str, *, limit: int = 50) -> list[GlossaryEntryRecord]:
        normalized_work_id = normalize_mysql_work_id(work_id)
        normalized_country = normalize_target_country(target_country) or ""
        query = (
            "SELECT * FROM glossary "
            "WHERE work_id=%s AND target_country=%s "
            "ORDER BY original_word, glossary_type"
        )
        params: tuple[Any, ...] = (normalized_work_id, normalized_country)
        if int(limit) > 0:  # limit<=0 → 무제한(LIMIT 절 생략; MySQL LIMIT 0은 0행이므로)
            query += " LIMIT %s"
            params += (int(limit),)
        with self._connect() as conn, self._cursor(conn) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_entry(self, entry_id: int) -> GlossaryEntryRecord | None:
        with self._connect() as conn, self._cursor(conn) as cur:
            cur.execute("SELECT * FROM glossary WHERE glossary_id=%s", (int(entry_id),))
            row = cur.fetchone()
        return self._row_to_entry(row) if row else None

    def delete_entry(self, entry_id: int) -> bool:
        with self._connect() as conn:
            try:
                with self._cursor(conn) as cur:
                    cur.execute("DELETE FROM glossary WHERE glossary_id=%s", (int(entry_id),))
                    deleted = cur.rowcount > 0
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return deleted

    def hydrate_work_memory(self, work_id: str, target_country: str, *, limit: int = 0) -> WorkMemory | None:
        records = self.list_glossary(work_id, target_country, limit=limit)
        return hydrate_work_memory_from_records(work_id, target_country, records, limit=limit)

    @staticmethod
    def _row_to_entry(row: dict[str, Any]) -> GlossaryEntryRecord:
        glossary_type = str(row.get("glossary_type") or DEFAULT_CATEGORY)
        memo = row.get("memo")
        return GlossaryEntryRecord(
            glossary_id=int(row["glossary_id"]),
            work_id=str(row["work_id"]),
            target_country=str(row["target_country"]),
            original_word=str(row["original_word"]),
            translated_word=str(row["translated_word"]),
            glossary_type=glossary_type if glossary_type in GLOSSARY_CATEGORIES else DEFAULT_CATEGORY,
            memo=str(memo) if memo is not None else None,
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


def as_debug_dict(row: Any) -> dict[str, Any]:
    return asdict(row) if hasattr(row, "__dataclass_fields__") else dict(row or {})
