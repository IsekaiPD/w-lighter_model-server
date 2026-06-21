"""저장소 인터페이스 — 작품/회차/캐릭터/번역/관계도/가이드/표지/채팅 영속화.

rdb 비활성(content_store_backend=memory)이면 쓰기는 graceful no-op, 읽기는 빈 결과.
glossary hydrate는 `domains/translation/glossary/` 추상화에 위임한다.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any

from core.logging import get_logger
from common.limits import (
    MAX_COVERS_PER_WORK,
    MAX_GUIDES_PER_WORK,
    MAX_RELATION_MAPS_PER_WORK,
    MAX_TRANSLATION_VERSIONS,
)

from .session import get_session, rdb_enabled

logger = get_logger("db.repository")


# ------------------------------------------------------------------ #
# 정규화 헬퍼 (ERD 제약에 맞춤)
# ------------------------------------------------------------------ #
def _s(value: Any) -> str:
    return str(value or "").strip()


def _trunc(value: Any, max_len: int) -> str:
    """ERD VARCHAR 길이에 맞춰 안전 절단(MySQL은 초과 시 에러). 빈값은 ''."""
    text = _s(value)
    return text[:max_len].rstrip() if len(text) > max_len else text


def _json_dump(value: Any) -> str:
    """TEXT 컬럼 저장용 JSON 문자열. 이미 문자열이면 그대로 둔다."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _bool_int(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    text = _s(value).lower()
    return 1 if text in {"1", "true", "yes", "y", "on"} else 0


def _prune_old_rows(session, model, filters: list[Any], order_column: Any, keep: int) -> None:
    """최신 keep개만 남기고 오래된 저장 결과를 삭제한다.

    요구사항 기준 보관 개수 제한:
    - 번역: 회차 × 국가별 최근 3개
    - 표지: 작품당 5장
    - 관계도: 작품당 3개
    - 가이드: 작품당 5개
    """
    if keep <= 0:
        return
    old_rows = (
        session.query(model)
        .filter(*filters)
        .order_by(order_column.desc())
        .offset(keep)
        .all()
    )
    for row in old_rows:
        session.delete(row)


_PROFILE_LABEL_RE = re.compile(r"^\s*프로필\s*라벨\s*:\s*(.+?)\s*$", re.MULTILINE)
_DETAIL_PREFIX_RE = re.compile(r"^\s*세부\s*설정\s*:\s*", re.MULTILINE)


def split_profile_label(detail_setting: Any) -> tuple[str, str]:
    """detail_setting에 묻어둔 profile_label을 분리한다.

    DB 컬럼 추가 없이 아래 고정 포맷을 사용한다.
    프로필 라벨: 전직 형사
    세부 설정: ...
    """
    detail = _s(detail_setting)
    if not detail:
        return "", ""
    match = _PROFILE_LABEL_RE.search(detail)
    profile_label = match.group(1).strip() if match else ""
    cleaned = _PROFILE_LABEL_RE.sub("", detail).strip()
    cleaned = _DETAIL_PREFIX_RE.sub("", cleaned).strip()
    return profile_label, cleaned


def pack_profile_label(profile_label: Any, detail_setting: Any, *, max_len: int = 1000) -> str:
    """profile_label을 detail_setting에 고정 포맷으로 합쳐 저장한다."""
    label = _trunc(profile_label, 80)
    detail = _s(detail_setting)
    existing_label, cleaned_detail = split_profile_label(detail)
    if not label:
        label = existing_label
    if not cleaned_detail:
        cleaned_detail = detail if not existing_label else ""
    if label:
        combined = f"프로필 라벨: {label}"
        if cleaned_detail:
            combined += f"\n세부 설정: {cleaned_detail}"
    else:
        combined = cleaned_detail or detail
    return _trunc(combined, max_len)


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

    profile_label은 화면/DB 컬럼 추가를 피하기 위해 detail_setting에 묻어 저장한다.
    """
    return {
        "char_name": _trunc(raw.get("char_name"), 30),
        "gender": normalize_gender(raw.get("gender")),
        "age": _trunc(raw.get("age"), 10),
        "role": _trunc(raw.get("role"), 5),  # ERD VARCHAR(5) — extraction(≤10)보다 짧으므로 절단
        "appearance": _trunc(raw.get("appearance"), 300),
        "relationships": _trunc(raw.get("relationships"), 500),
        "detail_setting": pack_profile_label(raw.get("profile_label"), raw.get("detail_setting"), max_len=1000),
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
# characters
# ------------------------------------------------------------------ #
def save_characters(work_id: int, characters: list[dict[str, Any]]) -> dict[str, Any]:
    """character_extract 결과를 CHARACTERS에 적재 → {saved, count, character_ids}.

    work_id FK가 없으면 graceful 실패. gender/role/길이는 ERD에 맞춰 정규화.
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
        results: list[dict[str, Any]] = []
        for r in rows:
            profile_label, cleaned_detail = split_profile_label(r.detail_setting)
            results.append(
                {
                    "character_id": r.character_id,
                    "work_id": r.work_id,
                    "char_name": r.char_name,
                    "gender": r.gender,
                    "age": r.age,
                    "role": r.role,
                    "appearance": r.appearance,
                    "relationships": r.relationships,
                    # API/LLM용으로는 profile_label을 복원해 넘긴다.
                    "profile_label": profile_label,
                    # 관계도/표지 프롬프트에는 라벨 줄을 제거한 세부 설정만 전달한다.
                    "detail_setting": cleaned_detail or r.detail_setting,
                    # 디버깅/이관용 원본. 화면에서 필요 없으면 무시 가능.
                    "detail_setting_raw": r.detail_setting,
                }
            )
        return results
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
        session.flush()
        _prune_old_rows(
            session,
            TranslationResult,
            [
                TranslationResult.episode_id == int(episode_id),
                TranslationResult.target_country == _trunc(country, 2).upper(),
            ],
            TranslationResult.translation_id,
            MAX_TRANSLATION_VERSIONS,
        )
        session.commit()
        session.refresh(row)
        return {"saved": True, "translation_id": row.translation_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ------------------------------------------------------------------ #
# relation_maps / localization_guides / covers / chat_messages
# ------------------------------------------------------------------ #
def save_relation_map(*, work_id: int, map_content: Any) -> dict[str, Any]:
    """관계도 결과 저장 → {saved, map_id}. map_content는 HTML 문자열 또는 JSON 직렬화 대상."""
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled"}
    from .models import RelationMap, Work

    session = get_session()
    try:
        if session.get(Work, int(work_id)) is None:
            return {"saved": False, "reason": f"work_id {work_id} not found"}
        row = RelationMap(work_id=int(work_id), map_content=_json_dump(map_content))
        session.add(row)
        session.flush()
        _prune_old_rows(
            session,
            RelationMap,
            [RelationMap.work_id == int(work_id)],
            RelationMap.map_id,
            MAX_RELATION_MAPS_PER_WORK,
        )
        session.commit()
        session.refresh(row)
        return {"saved": True, "map_id": row.map_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_localization_guide(*, work_id: int, target_country: str | None, guide_content: Any) -> dict[str, Any]:
    """현지화 가이드 저장 → {saved, guide_id}."""
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled"}
    from .models import LocalizationGuide, Work

    session = get_session()
    try:
        if session.get(Work, int(work_id)) is None:
            return {"saved": False, "reason": f"work_id {work_id} not found"}
        country = _s(target_country).upper() or None
        row = LocalizationGuide(
            work_id=int(work_id),
            target_country=_trunc(country, 2) if country else None,
            guide_content=_json_dump(guide_content),
        )
        session.add(row)
        session.flush()
        _prune_old_rows(
            session,
            LocalizationGuide,
            [LocalizationGuide.work_id == int(work_id)],
            LocalizationGuide.guide_id,
            MAX_GUIDES_PER_WORK,
        )
        session.commit()
        session.refresh(row)
        return {"saved": True, "guide_id": row.guide_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_cover(*, work_id: int, target_country: str, cover_url: str, main_cover_yn: Any = False) -> dict[str, Any]:
    """표지 저장 → {saved, cover_id}. cover_url은 ERD상 VARCHAR(255)이므로 URL/파일 경로만 저장한다."""
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled"}
    if not _s(cover_url):
        return {"saved": False, "reason": "cover_url is required"}
    from .models import Cover, Work

    session = get_session()
    try:
        if session.get(Work, int(work_id)) is None:
            return {"saved": False, "reason": f"work_id {work_id} not found"}
        row = Cover(
            work_id=int(work_id),
            cover_url=_trunc(cover_url, 255),
            target_country=_trunc(_s(target_country).upper() or "KR", 2),
            main_cover_yn=_bool_int(main_cover_yn),
        )
        session.add(row)
        session.flush()
        _prune_old_rows(
            session,
            Cover,
            [Cover.work_id == int(work_id)],
            Cover.cover_id,
            MAX_COVERS_PER_WORK,
        )
        session.commit()
        session.refresh(row)
        return {"saved": True, "cover_id": row.cover_id, "cover_url": row.cover_url}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_chat_messages(*, translation_id: int, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """검수 챗봇 메시지 묶음 저장 → {saved, count, message_ids}."""
    if not rdb_enabled():
        return {"saved": False, "count": 0, "message_ids": [], "reason": "persistence_disabled"}
    if not messages:
        return {"saved": True, "count": 0, "message_ids": []}
    from .models import ChatMessage, TranslationResult

    session = get_session()
    try:
        if session.get(TranslationResult, int(translation_id)) is None:
            return {"saved": False, "count": 0, "message_ids": [], "reason": f"translation_id {translation_id} not found"}
        rows: list[ChatMessage] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            sender = _s(item.get("sender_type") or item.get("senderType")).upper()
            if sender not in {"USER", "ASSISTANT"}:
                continue
            message_text = str(item.get("message_text") or item.get("messageText") or "").strip()
            if not message_text:
                continue
            rows.append(ChatMessage(translation_id=int(translation_id), sender_type=sender, message_text=message_text))
        if not rows:
            return {"saved": True, "count": 0, "message_ids": []}
        session.add_all(rows)
        session.commit()
        ids = [r.message_id for r in rows]
        return {"saved": True, "count": len(ids), "message_ids": ids}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ------------------------------------------------------------------ #
# glossary hydrate (기존 추상화에 위임)
# ------------------------------------------------------------------ #
def _glossary_repository():
    """설정에 맞는 GlossaryRepository 선택.

    - mysql: MySQLGlossaryRepository(raw PyMySQL, glossary 전용 스키마).
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
    """승인 glossary로 WorkMemory를 hydrate → 엔진용 dict(없으면 None).

    엔진은 work_memory를 dict로 받아 approvedGlossary를 읽으므로 asdict로 변환해 반환한다.
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
