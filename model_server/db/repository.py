"""저장소 인터페이스 — 작품/회차/캐릭터/번역/관계도/가이드/표지/채팅 영속화.

rdb 비활성(content_store_backend=memory)이면 쓰기는 graceful no-op, 읽기는 빈 결과.
glossary hydrate는 `domains/translation/glossary/` 추상화에 위임한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from common.limits import (
    MAX_COVERS_PER_WORK,
    MAX_GUIDES_PER_WORK,
    MAX_RELATION_MAPS_PER_WORK,
    MAX_TRANSLATION_VERSIONS,
)
from core.logging import get_logger

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


def _prune_old_rows(
    session, model, filters: list[Any], order_column: Any, keep: int
) -> None:
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


_PROFILE_DETAIL_INLINE_RE = re.compile(
    r"^\s*프로필\s*라벨\s*:\s*(?P<label>.*?)\s*세부\s*설정\s*:\s*(?P<detail>.*)\s*$",
    re.DOTALL,
)
_PROFILE_LABEL_RE = re.compile(
    r"^\s*프로필\s*라벨\s*:\s*(?P<label>.+?)\s*$", re.MULTILINE
)
_DETAIL_PREFIX_RE = re.compile(r"^\s*세부\s*설정\s*:\s*", re.MULTILINE)


def split_profile_label(detail_setting: Any) -> tuple[str, str]:
    """구버전 detail_setting에 묻힌 profile_label을 읽기 호환용으로 분리한다.

    신규 저장은 characters.profile_label 컬럼을 사용하며,
    detail_setting에는 캐릭터 세부 설정만 저장한다.
    """
    detail = _s(detail_setting)
    if not detail:
        return "", ""

    inline_match = _PROFILE_DETAIL_INLINE_RE.match(detail)
    if inline_match:
        return inline_match.group("label").strip(), inline_match.group("detail").strip()

    match = _PROFILE_LABEL_RE.search(detail)
    profile_label = match.group("label").strip() if match else ""
    cleaned = _PROFILE_LABEL_RE.sub("", detail).strip()
    cleaned = _DETAIL_PREFIX_RE.sub("", cleaned).strip()
    return profile_label, cleaned


def format_profile_detail(profile_label: Any, detail_setting: Any) -> str:
    """캐릭터 설정 화면용 세부 설정 문자열. profile_label은 섞지 않는다."""
    return _s(detail_setting)


def normalize_profile_fields(
    profile_label: Any, detail_setting: Any
) -> tuple[str, str]:
    """profile_label 컬럼값과 detail_setting 본문을 분리해 정규화한다."""
    label = _trunc(profile_label, 80)
    legacy_label, cleaned_detail = split_profile_label(detail_setting)
    return label or _trunc(legacy_label, 80), _trunc(cleaned_detail, 1000)


_GENDER_M = {"m", "male", "남", "남자", "남성", "사내", "boy", "man"}
_GENDER_F = {"f", "female", "여", "여자", "여성", "girl", "woman"}


def normalize_gender(value: Any) -> str:
    """자유 텍스트 성별 → DB 저장용 코드(M/F/U)로 정규화한다.

    characters.gender는 M/F/U만 허용(ERD CHECK). 한글 표시값(남/여/미상)은 응답 단계에서
    display_gender로 따로 변환한다. (M/M·남/male… → M, F/여/female… → F, 그 외 → U)
    """
    token = _s(value).lower()
    if token in _GENDER_M:
        return "M"
    if token in _GENDER_F:
        return "F"
    return "U"


def _map_character(raw: dict[str, Any]) -> dict[str, Any]:
    """character_extract 출력 1건 → CHARACTERS 컬럼 dict."""
    profile_label, detail_setting = normalize_profile_fields(
        raw.get("profile_label"), raw.get("detail_setting")
    )
    return {
        "char_name": _trunc(raw.get("char_name"), 30),
        "gender": normalize_gender(raw.get("gender")),
        "age": _trunc(raw.get("age"), 10),
        "role": _trunc(
            raw.get("role"), 5
        ),  # ERD VARCHAR(5) — extraction(≤10)보다 짧으므로 절단
        "profile_label": profile_label,
        "appearance": _trunc(raw.get("appearance"), 300),
        "relationships": _trunc(raw.get("relationships"), 500),
        "detail_setting": detail_setting,
    }


# ------------------------------------------------------------------ #
# works / episodes
# ------------------------------------------------------------------ #
def create_work(
    *,
    title: str = "",
    genre: str = "",
    synopsis: str | None = None,
    pen_name: str = "",
    user_id: int | None = None,
) -> dict[str, Any]:
    """작품 1건 생성 → {work_id, ...}. rdb 비활성이면 saved=False."""
    if not rdb_enabled():
        return {
            "saved": False,
            "reason": "persistence_disabled (content_store_backend=memory)",
        }
    from .models import Work

    session = get_session()
    try:
        work = Work(
            title=_trunc(title, 50),
            genre=_trunc(genre, 10),
            synopsis=synopsis,
            pen_name=_trunc(pen_name, 10),
            user_id=user_id,
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
            "work_id": work.work_id,
            "user_id": work.user_id,
            "title": work.title,
            "pen_name": work.pen_name,
            "genre": work.genre,
            "synopsis": work.synopsis,
        }
    finally:
        session.close()


def create_episode(
    *, work_id: int, title: str = "", original_text: str = ""
) -> dict[str, Any]:
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled"}
    from .models import Episode

    session = get_session()
    try:
        ep = Episode(
            work_id=int(work_id),
            title=_trunc(title, 30),
            original_text=_trunc(original_text, 8000),
        )
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
        return {
            "saved": False,
            "count": 0,
            "character_ids": [],
            "reason": "persistence_disabled",
        }
    if not characters:
        return {"saved": True, "count": 0, "character_ids": []}
    from .models import Character, Work

    session = get_session()
    try:
        if session.get(Work, int(work_id)) is None:
            return {
                "saved": False,
                "count": 0,
                "character_ids": [],
                "reason": f"work_id {work_id} not found",
            }
        rows = [
            Character(work_id=int(work_id), **_map_character(c))
            for c in characters
            if isinstance(c, dict)
        ]
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
        rows = (
            session.execute(
                select(Character)
                .where(Character.work_id == int(work_id))
                .order_by(Character.character_id)
            )
            .scalars()
            .all()
        )
        results: list[dict[str, Any]] = []
        for r in rows:
            legacy_label, cleaned_detail = split_profile_label(r.detail_setting)
            profile_label = _trunc(getattr(r, "profile_label", "") or legacy_label, 80)
            detail_setting = cleaned_detail or _s(r.detail_setting)
            results.append(
                {
                    "character_id": r.character_id,
                    "work_id": r.work_id,
                    "char_name": r.char_name,
                    "gender": r.gender,
                    "age": r.age,
                    "role": r.role,
                    "profile_label": profile_label,
                    "appearance": r.appearance,
                    "relationships": r.relationships,
                    "detail_setting": detail_setting,
                    "detail_setting_display": format_profile_detail(
                        profile_label, detail_setting
                    ),
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
        return {
            "saved": False,
            "reason": "persistence_disabled (content_store_backend=memory)",
        }

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
            annotation_can=payload.get("annotationCan")
            or payload.get("annotation_can"),
            inspection_report=payload.get("inspectionReport")
            or payload.get("inspection_report"),
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


def get_work_id_by_episode(episode_id: int) -> int | None:
    """episode_id로 work_id 조회."""
    if not rdb_enabled():
        return None
    from .models import Episode

    session = get_session()
    try:
        ep = session.get(Episode, int(episode_id))
        return ep.work_id if ep else None
    finally:
        session.close()


def get_translation_result(translation_id: int) -> dict[str, Any] | None:
    """번역 결과 단건 조회 → dict. rdb 비활성이거나 해당 ID 없으면 None."""
    if not rdb_enabled():
        return None
    from .models import TranslationResult

    session = get_session()
    try:
        row = session.get(TranslationResult, int(translation_id))
        if row is None:
            return None
        return {
            "translation_id": row.translation_id,
            "episode_id": row.episode_id,
            "target_country": row.target_country,
            "translated_text": row.translated_text,
            "summary": row.summary,
            "glossary_can": row.glossary_can,
            "annotation_can": row.annotation_can,
            "inspection_report": row.inspection_report,
        }
    finally:
        session.close()


def update_translation_text(translation_id: int, new_text: str) -> dict[str, Any]:
    """챗봇 승인 후 번역문 본문 업데이트 → {saved, translation_id}."""
    if not rdb_enabled():
        return {"saved": False, "reason": "persistence_disabled"}
    from .models import TranslationResult

    session = get_session()
    try:
        row = session.get(TranslationResult, int(translation_id))
        if row is None:
            return {
                "saved": False,
                "reason": f"translation_id {translation_id} not found",
            }
        row.translated_text = str(new_text)
        session.commit()
        return {"saved": True, "translation_id": translation_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_glossary_entry(
    *,
    work_id: str,
    target_country: str,
    original_word: str,
    translated_word: str,
    glossary_type: str = "",
) -> dict[str, Any]:
    """glossary 항목 upsert → {saved, glossary_id}. mysql 백엔드만 지원."""
    try:
        repo = _glossary_repository()
        if not hasattr(repo, "upsert_entry"):
            return {
                "saved": False,
                "reason": "glossary store does not support upsert (mysql 백엔드 필요)",
            }
        record = repo.upsert_entry(
            work_id=str(work_id),
            target_country=target_country,
            original_word=original_word,
            translated_word=translated_word,
            glossary_type=glossary_type or "",
        )
        return {"saved": True, "glossary_id": record.glossary_id}
    except Exception as exc:  # noqa: BLE001
        logger.warning("upsert_glossary_entry failed: %r", exc)
        return {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}


def delete_glossary_entry_by_word(
    *,
    work_id: str,
    target_country: str,
    original_word: str,
) -> dict[str, Any]:
    """원어로 glossary 항목 전체 삭제 → {saved, deleted_count}."""
    try:
        repo = _glossary_repository()
        if not hasattr(repo, "list_glossary") or not hasattr(repo, "delete_entry"):
            return {"saved": False, "reason": "glossary store does not support delete"}
        records = repo.list_glossary(str(work_id), target_country, limit=0)
        targets = [r for r in records if r.original_word == original_word]
        if not targets:
            return {
                "saved": False,
                "reason": f"'{original_word}'을(를) glossary에서 찾을 수 없습니다.",
            }
        for r in targets:
            repo.delete_entry(r.glossary_id)
        return {"saved": True, "deleted_count": len(targets)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_glossary_entry_by_word failed: %r", exc)
        return {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}


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


def save_localization_guide(
    *, work_id: int, target_country: str | None, guide_content: Any
) -> dict[str, Any]:
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


def save_cover(
    *, work_id: int, target_country: str, cover_url: str, main_cover_yn: Any = False
) -> dict[str, Any]:
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


def save_chat_messages(
    *, translation_id: int, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """검수 챗봇 메시지 묶음 저장 → {saved, count, message_ids}."""
    if not rdb_enabled():
        return {
            "saved": False,
            "count": 0,
            "message_ids": [],
            "reason": "persistence_disabled",
        }
    if not messages:
        return {"saved": True, "count": 0, "message_ids": []}
    from .models import ChatMessage, TranslationResult

    session = get_session()
    try:
        if session.get(TranslationResult, int(translation_id)) is None:
            return {
                "saved": False,
                "count": 0,
                "message_ids": [],
                "reason": f"translation_id {translation_id} not found",
            }
        rows: list[ChatMessage] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            sender = _s(item.get("sender_type") or item.get("senderType")).upper()
            if sender not in {"USER", "ASSISTANT"}:
                continue
            message_text = str(
                item.get("message_text") or item.get("messageText") or ""
            ).strip()
            if not message_text:
                continue
            rows.append(
                ChatMessage(
                    translation_id=int(translation_id),
                    sender_type=sender,
                    message_text=message_text,
                )
            )
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
    """glossary 저장소 선택 — DATABASE_URL(또는 MYSQL_*)로 접속되면 MySQL, 아니면 in-memory.

    접속정보(DATABASE_URL/MYSQL_*)가 있으면 **항상 MySQL**을 쓰고, 없거나 드라이버/연결이 안 되면
    (로컬·테스트) 자동으로 in-memory로 폴백한다. 즉 "DB가 있으면 DB, 없으면 메모리"를 코드가 결정.
    """
    from domains.translation.glossary import default_glossary_repository

    try:
        from domains.translation.glossary.mysql_store import MySQLGlossaryRepository

        return (
            MySQLGlossaryRepository.from_env()
        )  # DATABASE_URL/MYSQL_* 있으면 MySQL, 없으면 예외 → 폴백
    except Exception as exc:  # noqa: BLE001 — 드라이버/접속정보 미비 → in-memory 폴백
        logger.warning("glossary MySQL backend unavailable, using in-memory: %r", exc)
    return default_glossary_repository


def hydrate_work_memory(work_id: str, country: str) -> dict[str, Any] | None:
    """승인 glossary로 WorkMemory를 hydrate → 엔진용 dict(없으면 None).

    엔진은 work_memory를 dict로 받아 approvedGlossary를 읽으므로 asdict로 변환해 반환한다.
    """
    try:
        repo = _glossary_repository()
        # limit=0 → 상한 없이 작품 glossary 전량 로드. 회차 관련 용어 선별은
        # 엔진의 load_work_memory 노드가 원문 등장 여부로 결정론 필터링한다.
        wm = repo.hydrate_work_memory(_s(work_id), _s(country), limit=0)
    except Exception as exc:  # noqa: BLE001 — hydrate 실패가 번역을 막지 않도록
        logger.warning("hydrate_work_memory failed: %r", exc)
        return None
    if wm is None:
        return None
    return asdict(wm)
