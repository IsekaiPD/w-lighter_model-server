from __future__ import annotations

import importlib
import os
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
    """Load an installed MySQL DB-API driver without requiring a dependency.

    Preference is PyMySQL because it is pure Python and declared in
    requirements.txt, then mysql-connector-python if present.
    """

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


class MySQLGlossaryRepository(GlossaryRepository):
    """MySQL 8.x implementation of the single-table glossary repository.

    Expected schema (created out-of-band, not migrated here)::

        CREATE TABLE glossary (
          id         BIGINT AUTO_INCREMENT PRIMARY KEY,
          work_id    BIGINT NOT NULL,            -- works.work_id
          country    VARCHAR(2) NOT NULL,        -- JP / US / CN / TH
          source     VARCHAR(255) NOT NULL,
          target     VARCHAR(255) NOT NULL,
          category   VARCHAR(16) NOT NULL,       -- person / place / organization
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uq_glossary (work_id, country, source, category)
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
        return cls()

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
        country: str,
        source: str,
        target: str,
        category: str,
    ) -> dict[str, Any]:
        normalized = {
            "work_id": normalize_mysql_work_id(work_id),
            "country": normalize_target_country(country) or "",
            "source": _clean(source),
            "target": _clean(target),
            "category": normalize_category(category),
        }
        if not normalized["country"] or not normalized["source"] or not normalized["target"]:
            raise ValueError("work_id, country, source, and target are required")
        if is_contextual_reference(normalized["source"]):
            raise ValueError("source is a contextual reference and should not be persisted as a glossary entry")
        return normalized

    def upsert_entry(
        self,
        *,
        work_id: str,
        country: str,
        source: str,
        target: str,
        category: str = DEFAULT_CATEGORY,
    ) -> GlossaryEntryRecord:
        payload = self._normalize_payload(
            work_id=work_id,
            country=country,
            source=source,
            target=target,
            category=category,
        )
        with self._connect() as conn:
            try:
                with self._cursor(conn) as cur:
                    cur.execute(
                        """
                        SELECT id FROM glossary
                        WHERE work_id=%s AND country=%s AND source=%s AND category=%s
                        LIMIT 1
                        """,
                        (payload["work_id"], payload["country"], payload["source"], payload["category"]),
                    )
                    existing = cur.fetchone()
                    if existing:
                        entry_id = int(existing["id"])
                        cur.execute(
                            "UPDATE glossary SET target=%s WHERE id=%s",
                            (payload["target"], entry_id),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO glossary (work_id, country, source, target, category)
                            VALUES (%s,%s,%s,%s,%s)
                            """,
                            (
                                payload["work_id"],
                                payload["country"],
                                payload["source"],
                                payload["target"],
                                payload["category"],
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

    def list_glossary(self, work_id: str, country: str, *, limit: int = 50) -> list[GlossaryEntryRecord]:
        normalized_work_id = normalize_mysql_work_id(work_id)
        normalized_country = normalize_target_country(country) or ""
        with self._connect() as conn, self._cursor(conn) as cur:
            cur.execute(
                """
                SELECT * FROM glossary
                WHERE work_id=%s AND country=%s
                ORDER BY source, category
                LIMIT %s
                """,
                (normalized_work_id, normalized_country, max(0, int(limit))),
            )
            rows = cur.fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_entry(self, entry_id: int) -> GlossaryEntryRecord | None:
        with self._connect() as conn, self._cursor(conn) as cur:
            cur.execute("SELECT * FROM glossary WHERE id=%s", (int(entry_id),))
            row = cur.fetchone()
        return self._row_to_entry(row) if row else None

    def delete_entry(self, entry_id: int) -> bool:
        with self._connect() as conn:
            try:
                with self._cursor(conn) as cur:
                    cur.execute("DELETE FROM glossary WHERE id=%s", (int(entry_id),))
                    deleted = cur.rowcount > 0
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return deleted

    def hydrate_work_memory(self, work_id: str, country: str, *, limit: int = 50) -> WorkMemory | None:
        records = self.list_glossary(work_id, country, limit=limit)
        return hydrate_work_memory_from_records(work_id, country, records, limit=limit)

    @staticmethod
    def _row_to_entry(row: dict[str, Any]) -> GlossaryEntryRecord:
        category = str(row.get("category") or DEFAULT_CATEGORY)
        return GlossaryEntryRecord(
            id=int(row["id"]),
            work_id=str(row["work_id"]),
            country=str(row["country"]),
            source=str(row["source"]),
            target=str(row["target"]),
            category=category if category in GLOSSARY_CATEGORIES else DEFAULT_CATEGORY,
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )


def as_debug_dict(row: Any) -> dict[str, Any]:
    return asdict(row) if hasattr(row, "__dataclass_fields__") else dict(row or {})
