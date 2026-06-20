"""저장소 인터페이스 — works/episodes/characters/translation_results 영속화 + glossary hydrate 위임.

설계 원칙:
- 모델/세션은 포터블(SQLite 로컬 ↔ MySQL 배포는 DATABASE_URL로만 전환; `db/session.py`).
- rdb 비활성(content_store_backend=memory)이면 쓰기 계열은 graceful no-op, 읽기는 빈 결과.
- glossary는 재작성하지 않는다 — 기존 `domains/translation/glossary/` 추상화(InMemory/MySQL
  repository + WorkMemory 변환)에 hydrate를 **위임**한다.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.logging import get_logger

from .session import get_session, rdb_enabled

logger = get_logger("db.repository")


# ------------------------------------------------------------------ #
# 정규화 헬퍼 (ERD 제약에 맞춤 — "틀리지 않게")
# ------------------------------------------------------------------ #
def _s(value: Any) -> str:
    return str(value or "").strip()


def _trunc(value: Any, max_len: int) -> str:
    """ERD VARCHAR 길이에 맞춰 안전 절단(MySQL은 초과 시 에러). 빈값은 ''."""
    text = _s(value)
    return text[:max_len].rstrip() if len(text) > max_len else text


_GENDER_M = {"m", "male", "남", "남자", "남성", "사내", "boy", "man"}
_GENDER_F = {"f", "female", "여", "여자", "여성", "girl", "woman"}


def normalize_gender(value: Any) -> str:
    """자유 텍스트 성별 → ERD CHECK(M/F/U). 미상/불명은 U."""
    token = _s(value).lower()
    if token in _GENDER_M:
        return "M"
    if token in _GENDER_F:
        return "F"
    return "U"


def _map_character(raw: dict[str, Any]) -> dict[str, Any]:
    """character_extract 출력 1건 → CHARACTERS 컬럼 dict.

    appearance→apperance(컬럼)는 ORM 속성명 appearance로 대입.
    profile_label은 ERD 컬럼 없음 → 미저장.
    """
    return {
        "char_name": _trunc(raw.get("char_name"), 30),
        "gender": normalize_gender(raw.get("gender")),
        "age": _trunc(raw.get("age"), 10),
        "role": _trunc(raw.get("role"), 5),  # ERD VARCHAR(5) — extraction(≤10)보다 짧으므로 절단
        "appearance": _trunc(raw.get("appearance"), 300),
        "relationships": _trunc(raw.get("relationships"), 500),
        "detail_setting": _trunc(raw.get("detail_setting"), 1000),
    }


# ------------------------------------------------------------------ #
# works / episodes
# ------------------------------------------------------------------ #
def create_work(
    *, title: str = "", genre: str = "", synopsis: str | None = None,
    pen_name: str = "", user_id: int | None = None,
) -> dict[str, Any]:
    """작품 1건 생성 → {work_id, ...}. rdb 비활성이면 saved=False."""
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled (content_store_backend=memory)"}
    from .models import Work

    session = get_session()
    try:
        work = Work(
            title=_trunc(title, 50), genre=_trunc(genre, 10),
            synopsis=synopsis, pen_name=_trunc(pen_name, 10), user_id=user_id,
        )
        session.add(work)
        session.commit()
        session.refresh(work)
        return {"saved": True, "work_id": work.work_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_work(work_id: int) -> dict[str, Any] | None:
    if not rdb_enabled():
        return None
    from .models import Work

    session = get_session()
    try:
        work = session.get(Work, int(work_id))
        if work is None:
            return None
        return {
            "work_id": work.work_id, "user_id": work.user_id, "title": work.title,
            "pen_name": work.pen_name, "genre": work.genre, "synopsis": work.synopsis,
        }
    finally:
        session.close()


def create_episode(*, work_id: int, title: str = "", original_text: str = "") -> dict[str, Any]:
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled"}
    from .models import Episode

    session = get_session()
    try:
        ep = Episode(work_id=int(work_id), title=_trunc(title, 30), original_text=_trunc(original_text, 8000))
        session.add(ep)
        session.commit()
        session.refresh(ep)
        return {"saved": True, "episode_id": ep.episode_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ------------------------------------------------------------------ #
# characters (character_extract 결과 적재)
# ------------------------------------------------------------------ #
def save_characters(work_id: int, characters: list[dict[str, Any]]) -> dict[str, Any]:
    """character_extract 결과를 CHARACTERS에 적재 → {saved, count, character_ids}.

    work_id FK는 존재해야 한다(없으면 graceful 실패). gender/role/길이는 ERD에 맞춰 정규화.
    """
    if not rdb_enabled():
        return {"saved": False, "count": 0, "character_ids": [], "reason": "persistence_disabled"}
    if not characters:
        return {"saved": True, "count": 0, "character_ids": []}
    from .models import Character, Work

    session = get_session()
    try:
        if session.get(Work, int(work_id)) is None:
            return {"saved": False, "count": 0, "character_ids": [], "reason": f"work_id {work_id} not found"}
        rows = [Character(work_id=int(work_id), **_map_character(c)) for c in characters if isinstance(c, dict)]
        session.add_all(rows)
        session.commit()
        ids = [r.character_id for r in rows]
        return {"saved": True, "count": len(ids), "character_ids": ids}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_characters(work_id: int) -> list[dict[str, Any]]:
    if not rdb_enabled():
        return []
    from sqlalchemy import select

    from .models import Character

    session = get_session()
    try:
        rows = session.execute(
            select(Character).where(Character.work_id == int(work_id)).order_by(Character.character_id)
        ).scalars().all()
        return [
            {
                "character_id": r.character_id, "work_id": r.work_id, "char_name": r.char_name,
                "gender": r.gender, "age": r.age, "role": r.role, "appearance": r.appearance,
                "relationships": r.relationships, "detail_setting": r.detail_setting,
            }
            for r in rows
        ]
    finally:
        session.close()


# ------------------------------------------------------------------ #
# translation_results
# ------------------------------------------------------------------ #
def save_translation_result(payload: dict[str, Any]) -> dict[str, Any]:
    """번역 결과 영속화 → {saved, translation_id}.

    필요한 키: episodeId/episode_id(FK, 존재해야 함), targetCountry(2자), translatedText.
    선택: summary, glossaryCan, annotationCan(예: readerEndnotes), inspectionReport(예: qaIssues).
    rdb 비활성/episode 부재/필수값 누락이면 graceful saved=False.
    """
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled (content_store_backend=memory)"}

    episode_id = payload.get("episodeId") or payload.get("episode_id")
    country = _s(payload.get("targetCountry") or payload.get("target_country"))
    translated = payload.get("translatedText") or payload.get("translated_text") or ""
    if not episode_id or not country:
        return {"saved": False, "reason": "episodeId and targetCountry are required"}

    from .models import Episode, TranslationResult

    session = get_session()
    try:
        if session.get(Episode, int(episode_id)) is None:
            return {"saved": False, "reason": f"episode_id {episode_id} not found"}
        row = TranslationResult(
            episode_id=int(episode_id),
            target_country=_trunc(country, 2).upper(),
            translated_text=str(translated or ""),
            summary=payload.get("summary"),
            glossary_can=payload.get("glossaryCan") or payload.get("glossary_can"),
            annotation_can=payload.get("annotationCan") or payload.get("annotation_can"),
            inspection_report=payload.get("inspectionReport") or payload.get("inspection_report"),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"saved": True, "translation_id": row.translation_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ------------------------------------------------------------------ #
# glossary hydrate (기존 추상화에 위임 — 재작성 X)
# ------------------------------------------------------------------ #
def _glossary_repository():
    """설정에 맞는 GlossaryRepository 선택.

    - mysql: 기존 MySQLGlossaryRepository(raw PyMySQL, glossary 전용 스키마).
    - 그 외(memory/rdb): 프로세스 메모리 기본 repo.
    NOTE: glossary의 SQLite/ERD 정렬은 미해결(ERD 컬럼명 vs 기존 코드 충돌) — TODO #2 참고.
    """
    from domains.translation.glossary import default_glossary_repository

    backend = "memory"
    try:
        from core.config import settings

        backend = (settings.glossary_store_backend or "memory").strip().lower()
    except Exception:  # noqa: BLE001
        pass

    if backend == "mysql":
        try:
            from domains.translation.glossary.mysql_store import MySQLGlossaryRepository

            return MySQLGlossaryRepository.from_env()
        except Exception as exc:  # noqa: BLE001 — 드라이버/설정 미비 → 메모리 폴백
            logger.warning("MySQL glossary backend unavailable, fallback to memory: %r", exc)
    return default_glossary_repository


def hydrate_work_memory(work_id: str, country: str) -> dict[str, Any] | None:
    """승인 glossary로 WorkMemory를 hydrate → 엔진용 **dict**(없으면 None).

    엔진(run_v3_literary_package)은 work_memory를 dict로 받아 approvedGlossary를 읽으므로
    WorkMemory dataclass를 asdict로 변환해 반환한다(dataclass 그대로 넘기면 무시됨).
    """
    try:
        repo = _glossary_repository()
        wm = repo.hydrate_work_memory(_s(work_id), _s(country))
    except Exception as exc:  # noqa: BLE001 — hydrate 실패가 번역을 막지 않도록
        logger.warning("hydrate_work_memory failed: %r", exc)
        return None
    if wm is None:
        return None
    return asdict(wm)
