"""Cover 도메인 서비스 — 표지 프롬프트/이미지 생성 엔진 오케스트레이션.

`cover_generate.generate_cover_image` 호출. dry_run이면 프롬프트만 반환한다.
workId가 있으면 DB의 작품/캐릭터를 보강하고, 생성 이미지(base64)는 S3 설정이 있으면 S3에 업로드한다.
S3 설정이 없으면 기존처럼 로컬 파일(`/generated/covers/...`)로 폴백한다.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.logging import get_logger
from db import repository as db_repo

from .cover_generate import generate_cover_image

logger = get_logger("cover.service")

_MODEL_SERVER_ROOT = Path(__file__).resolve().parents[2]
_COVER_DIR = _MODEL_SERVER_ROOT / "generated" / "covers"


def _should_save(payload: dict[str, Any]) -> bool:
    value = payload.get("saveCover")
    if value is None:
        value = payload.get("save_cover")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _main_cover_yn(payload: dict[str, Any]) -> Any:
    return payload.get("mainCoverYn") if "mainCoverYn" in payload else payload.get("main_cover_yn", False)


def _normalize_image_format(output_format: str) -> str:
    fmt = (output_format or "png").strip().lower().lstrip(".") or "png"
    return "jpg" if fmt == "jpeg" else fmt


def _cover_content_type(fmt: str) -> str:
    if fmt in {"jpg", "jpeg"}:
        return "image/jpeg"
    if fmt == "webp":
        return "image/webp"
    return "image/png"


def _cover_filename(*, work_id: int, target_country: str, output_format: str) -> str:
    fmt = _normalize_image_format(output_format)
    safe_country = (target_country or "KR").strip().upper()[:2] or "KR"
    date_part = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"work_{int(work_id)}_{safe_country}_{date_part}_{uuid4().hex[:8]}.{fmt}"


def _decode_image_base64(image_base64: str) -> bytes:
    raw = (image_base64 or "").strip()
    if not raw:
        raise ValueError("image_base64 is empty")
    # 혹시 data:image/png;base64,... 형태로 들어와도 처리한다.
    if "," in raw and raw.split(",", 1)[0].lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _s3_base_url(*, bucket: str, region: str) -> str:
    configured = (os.getenv("AWS_S3_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    return f"https://{bucket}.s3.{region}.amazonaws.com"


def _presigned_expires_seconds() -> int:
    raw = (os.getenv("AWS_S3_PRESIGNED_EXPIRES") or "3600").strip()
    try:
        value = int(raw)
    except ValueError:
        return 3600
    return max(60, min(value, 604800))  # S3 presigned GET URL 최대 7일


def _upload_generated_cover_to_s3(
    *,
    image_base64: str,
    work_id: int,
    target_country: str,
    output_format: str,
) -> dict[str, Any]:
    """base64 이미지를 S3에 업로드하고 영구 참조 URL과 presigned URL을 반환한다.

    AWS 자격증명은 EC2 IAM Role을 우선 사용한다. Access Key를 .env에 넣을 필요가 없다.
    """
    bucket = (os.getenv("AWS_S3_BUCKET_NAME") or "").strip()
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET_NAME is not set")

    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-northeast-2").strip()
    filename = _cover_filename(work_id=work_id, target_country=target_country, output_format=output_format)
    key_prefix = (os.getenv("AWS_S3_COVER_PREFIX") or "covers").strip().strip("/")
    key = f"{key_prefix}/{filename}" if key_prefix else filename
    fmt = _normalize_image_format(output_format)
    body = _decode_image_base64(image_base64)
    content_type = _cover_content_type(fmt)

    try:
        import boto3  # lazy import: boto3 미설치 로컬 환경에서도 dryRun/비표지 기능은 부팅 가능
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("boto3 is required for S3 cover upload. Add boto3 to requirements.txt") from exc

    s3 = boto3.client("s3", region_name=region)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )

    cover_url = f"{_s3_base_url(bucket=bucket, region=region)}/{key}"
    presigned_url = ""
    try:
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=_presigned_expires_seconds(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cover presigned url generation failed: %r", exc)

    return {
        "storage_backend": "s3",
        "cover_url": cover_url,          # DB 저장용 영구 참조 URL. private 버킷이면 직접 열람은 제한될 수 있음.
        "image_url": presigned_url or cover_url,  # 프론트 즉시 미리보기용.
        "presigned_cover_url": presigned_url,
        "s3_bucket": bucket,
        "s3_key": key,
        "s3_uri": f"s3://{bucket}/{key}",
        "content_type": content_type,
    }


def _save_generated_cover_file(
    *,
    image_base64: str,
    work_id: int,
    target_country: str,
    output_format: str,
) -> dict[str, Any]:
    """생성 이미지를 저장한다.

    AWS_S3_BUCKET_NAME이 있으면 S3 업로드를 사용하고, 없으면 기존 로컬 파일 저장 방식으로 폴백한다.
    """
    if (os.getenv("AWS_S3_BUCKET_NAME") or "").strip():
        return _upload_generated_cover_to_s3(
            image_base64=image_base64,
            work_id=work_id,
            target_country=target_country,
            output_format=output_format,
        )

    fmt = _normalize_image_format(output_format)
    filename = _cover_filename(work_id=work_id, target_country=target_country, output_format=fmt)
    _COVER_DIR.mkdir(parents=True, exist_ok=True)
    path = _COVER_DIR / filename
    path.write_bytes(_decode_image_base64(image_base64))
    cover_url = f"/generated/covers/{filename}"
    return {
        "storage_backend": "local",
        "cover_url": cover_url,
        "image_url": cover_url,
        "presigned_cover_url": "",
        "local_path": str(path),
        "content_type": _cover_content_type(fmt),
    }


def _apply_cover_save_result(result: dict[str, Any], save_result: dict[str, Any]) -> str:
    """저장 결과를 API 응답에 반영하고 DB에 저장할 cover_url을 반환한다."""
    cover_url = str(save_result.get("cover_url") or "")
    image_url = str(save_result.get("image_url") or cover_url)

    result["coverUrl"] = cover_url
    result["imageUrl"] = image_url
    result["coverStorage"] = save_result.get("storage_backend") or ""

    if save_result.get("presigned_cover_url"):
        result["presignedCoverUrl"] = save_result.get("presigned_cover_url")
    if save_result.get("s3_bucket"):
        result["s3Bucket"] = save_result.get("s3_bucket")
    if save_result.get("s3_key"):
        result["s3Key"] = save_result.get("s3_key")
    if save_result.get("s3_uri"):
        result["s3Uri"] = save_result.get("s3_uri")
    if save_result.get("local_path"):
        result["localPath"] = save_result.get("local_path")

    return cover_url


def generate_cover(payload: dict[str, Any]) -> dict[str, Any]:
    work_id = payload.get("workId") or payload.get("work_id")
    work = None
    if work_id is not None:
        try:
            work = db_repo.get_work(int(work_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover work lookup failed: %r", exc)

    characters = payload.get("characters") or []
    if not characters and work_id is not None:
        try:
            characters = db_repo.get_characters(int(work_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover character lookup failed: %r", exc)
            characters = []

    work_title = payload.get("workTitle") or payload.get("title") or (work or {}).get("title") or ""
    genre = payload.get("genre") or (work or {}).get("genre") or ""
    synopsis = payload.get("synopsis") or (work or {}).get("synopsis") or ""
    target_country = payload.get("targetCountry") or payload.get("target_country") or "KR"

    result = generate_cover_image(
        work_title=work_title,
        genre=genre,
        synopsis=synopsis,
        characters=characters,
        target_country=target_country,
        user_prompt=payload.get("userPrompt") or "",
        dry_run=bool(payload.get("dryRun", False)),
    )

    if work_id is not None and _should_save(payload):
        cover_url = (
            payload.get("coverUrl")
            or payload.get("cover_url")
            or payload.get("imageUrl")
            or payload.get("image_url")
            or result.get("coverUrl")
            or result.get("cover_url")
        )
        if not cover_url and result.get("image_base64"):
            try:
                save_result = _save_generated_cover_file(
                    image_base64=str(result.get("image_base64") or ""),
                    work_id=int(work_id),
                    target_country=str(result.get("target_country") or target_country),
                    output_format=str(result.get("output_format") or "png"),
                )
                cover_url = _apply_cover_save_result(result, save_result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cover image save failed: %r", exc)
                result["persistedCover"] = {"saved": False, "reason": f"image_save_failed: {type(exc).__name__}: {exc}"}
                return result
        try:
            result["persistedCover"] = db_repo.save_cover(
                work_id=int(work_id),
                target_country=str(result.get("target_country") or target_country),
                cover_url=str(cover_url or ""),
                main_cover_yn=_main_cover_yn(payload),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cover persistence failed: %r", exc)
            result["persistedCover"] = {"saved": False, "reason": f"{type(exc).__name__}: {exc}"}

    return result


def status() -> dict:
    return {"domain": "cover", "status": "wired", "endpoint": "POST /api/v1/cover"}
