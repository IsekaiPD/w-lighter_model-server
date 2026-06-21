"""개발/공개 테스트용 인메모리 IP Rate Limiter.

단일 EC2/단일 app 컨테이너 기준의 1차 비용 방어용이다.
컨테이너가 여러 개로 늘어나면 Redis 같은 외부 저장소 기반 limiter로 교체한다.
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

from fastapi import Request

from common.limits import (
    RATE_LIMIT_CHARACTER_EXTRACT_GLOBAL_PER_HOUR,
    RATE_LIMIT_CHARACTER_EXTRACT_IP_PER_HOUR,
    RATE_LIMIT_CHARACTER_EXTRACT_IP_PER_MINUTE,
    RATE_LIMIT_COVER_DRY_RUN_GLOBAL_PER_HOUR,
    RATE_LIMIT_COVER_DRY_RUN_IP_PER_HOUR,
    RATE_LIMIT_COVER_DRY_RUN_IP_PER_MINUTE,
    RATE_LIMIT_COVER_GENERATE_GLOBAL_PER_HOUR,
    RATE_LIMIT_COVER_GENERATE_IP_PER_HOUR,
    RATE_LIMIT_COVER_GENERATE_IP_PER_MINUTE,
    RATE_LIMIT_DEFAULT_IP_PER_HOUR,
    RATE_LIMIT_DEFAULT_IP_PER_MINUTE,
    RATE_LIMIT_GUIDE_GLOBAL_PER_HOUR,
    RATE_LIMIT_GUIDE_IP_PER_HOUR,
    RATE_LIMIT_GUIDE_IP_PER_MINUTE,
    RATE_LIMIT_INSPECT_CHAT_GLOBAL_PER_HOUR,
    RATE_LIMIT_INSPECT_CHAT_IP_PER_HOUR,
    RATE_LIMIT_INSPECT_CHAT_IP_PER_MINUTE,
    RATE_LIMIT_RELATIONSHIP_MAP_GLOBAL_PER_HOUR,
    RATE_LIMIT_RELATIONSHIP_MAP_IP_PER_HOUR,
    RATE_LIMIT_RELATIONSHIP_MAP_IP_PER_MINUTE,
    RATE_LIMIT_TRANSLATION_GLOBAL_PER_HOUR,
    RATE_LIMIT_TRANSLATION_IP_PER_HOUR,
    RATE_LIMIT_TRANSLATION_IP_PER_MINUTE,
)


@dataclass(frozen=True)
class RateRule:
    scope: str  # "ip" | "global"
    window_seconds: int
    limit: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0
    detail: str = "Rate limit exceeded. Please try again later."


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str, int], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, client_ip: str, rules: list[RateRule]) -> RateLimitDecision:
        if not rules:
            return RateLimitDecision(allowed=True)

        now = time.monotonic()
        with self._lock:
            for rule in rules:
                key_value = client_ip if rule.scope == "ip" else "global"
                key = (bucket, key_value, rule.window_seconds)
                q = self._hits[key]

                cutoff = now - rule.window_seconds
                while q and q[0] <= cutoff:
                    q.popleft()

                if len(q) >= rule.limit:
                    retry_after = max(1, int(q[0] + rule.window_seconds - now))
                    return RateLimitDecision(
                        allowed=False,
                        retry_after=retry_after,
                        detail=f"Rate limit exceeded for {bucket}. Please try again later.",
                    )

            for rule in rules:
                key_value = client_ip if rule.scope == "ip" else "global"
                key = (bucket, key_value, rule.window_seconds)
                self._hits[key].append(now)

        return RateLimitDecision(allowed=True)


rate_limiter = InMemoryRateLimiter()


def _client_ip(request: Request) -> str:
    # 현재 EC2에 FastAPI가 직접 노출된 구조에서는 X-Forwarded-For를 신뢰하면 spoofing 가능성이 있다.
    # ALB/Nginx 뒤로 옮기면 trusted proxy 설정을 별도로 두고 X-Forwarded-For를 사용한다.
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _is_dry_run(body: bytes) -> bool:
    if not body:
        return False
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return bool(payload.get("dryRun", False))


def rules_for_request(request: Request, body: bytes | None = None) -> tuple[str | None, list[RateRule]]:
    path = request.url.path
    method = request.method.upper()

    if method in {"OPTIONS", "HEAD"}:
        return None, []
    if path == "/health" or path.endswith("/_status"):
        return None, []
    if not path.startswith("/api/v1/"):
        return None, []

    default_rules = [
        RateRule("ip", 60, RATE_LIMIT_DEFAULT_IP_PER_MINUTE),
        RateRule("ip", 3600, RATE_LIMIT_DEFAULT_IP_PER_HOUR),
    ]

    if path == "/api/v1/translation/translate":
        return "translation", [
            RateRule("ip", 60, RATE_LIMIT_TRANSLATION_IP_PER_MINUTE),
            RateRule("ip", 3600, RATE_LIMIT_TRANSLATION_IP_PER_HOUR),
            RateRule("global", 3600, RATE_LIMIT_TRANSLATION_GLOBAL_PER_HOUR),
        ]

    if path == "/api/v1/translation/inspect-chat":
        return "inspect-chat", [
            RateRule("ip", 60, RATE_LIMIT_INSPECT_CHAT_IP_PER_MINUTE),
            RateRule("ip", 3600, RATE_LIMIT_INSPECT_CHAT_IP_PER_HOUR),
            RateRule("global", 3600, RATE_LIMIT_INSPECT_CHAT_GLOBAL_PER_HOUR),
        ]

    if path == "/api/v1/character-extract":
        return "character-extract", [
            RateRule("ip", 60, RATE_LIMIT_CHARACTER_EXTRACT_IP_PER_MINUTE),
            RateRule("ip", 3600, RATE_LIMIT_CHARACTER_EXTRACT_IP_PER_HOUR),
            RateRule("global", 3600, RATE_LIMIT_CHARACTER_EXTRACT_GLOBAL_PER_HOUR),
        ]

    if path == "/api/v1/relationship-map":
        return "relationship-map", [
            RateRule("ip", 60, RATE_LIMIT_RELATIONSHIP_MAP_IP_PER_MINUTE),
            RateRule("ip", 3600, RATE_LIMIT_RELATIONSHIP_MAP_IP_PER_HOUR),
            RateRule("global", 3600, RATE_LIMIT_RELATIONSHIP_MAP_GLOBAL_PER_HOUR),
        ]

    if path == "/api/v1/guide":
        return "guide", [
            RateRule("ip", 60, RATE_LIMIT_GUIDE_IP_PER_MINUTE),
            RateRule("ip", 3600, RATE_LIMIT_GUIDE_IP_PER_HOUR),
            RateRule("global", 3600, RATE_LIMIT_GUIDE_GLOBAL_PER_HOUR),
        ]

    if path == "/api/v1/cover":
        dry_run = _is_dry_run(body or b"")
        if dry_run:
            return "cover-dry-run", [
                RateRule("ip", 60, RATE_LIMIT_COVER_DRY_RUN_IP_PER_MINUTE),
                RateRule("ip", 3600, RATE_LIMIT_COVER_DRY_RUN_IP_PER_HOUR),
                RateRule("global", 3600, RATE_LIMIT_COVER_DRY_RUN_GLOBAL_PER_HOUR),
            ]
        return "cover-generate", [
            RateRule("ip", 60, RATE_LIMIT_COVER_GENERATE_IP_PER_MINUTE),
            RateRule("ip", 3600, RATE_LIMIT_COVER_GENERATE_IP_PER_HOUR),
            RateRule("global", 3600, RATE_LIMIT_COVER_GENERATE_GLOBAL_PER_HOUR),
        ]

    return "default", default_rules


async def read_body_and_replay(request: Request) -> bytes:
    """미들웨어에서 body를 읽은 뒤 downstream에서도 같은 body를 다시 읽을 수 있게 한다."""
    body = await request.body()

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = receive  # noqa: SLF001 - Starlette Request 재주입
    return body


def check_rate_limit(request: Request, body: bytes | None = None) -> RateLimitDecision:
    bucket, rules = rules_for_request(request, body)
    if not bucket:
        return RateLimitDecision(allowed=True)
    return rate_limiter.check(bucket=bucket, client_ip=_client_ip(request), rules=rules)
