"""미들웨어 설정 (CORS, 요청 본문 크기 제한 등)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from common.rate_limiter import check_rate_limit, read_body_and_replay


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def limit_request_body_size(request: Request, call_next):
        """Content-Length 기준으로 큰 요청을 OpenAI 호출 전에 차단한다.

        클라이언트가 Content-Length를 보내지 않는 스트리밍 요청까지 완전 차단하는 목적은 아니고,
        일반 JSON 요청에서 1차 비용/오남용 방어를 담당한다.
        """
        max_bytes = int(getattr(settings, "max_request_body_bytes", 512 * 1024))
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                if int(content_length) > max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large. Max {max_bytes} bytes allowed."},
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})

        return await call_next(request)

    @app.middleware("http")
    async def limit_request_rate(request: Request, call_next):
        """IP 기준 Rate Limit으로 공개 테스트 중 반복 호출/비용 폭탄을 줄인다."""
        if not bool(getattr(settings, "rate_limit_enabled", True)):
            return await call_next(request)

        body = b""
        if request.method.upper() in {"POST", "PUT", "PATCH"}:
            body = await read_body_and_replay(request)

        decision = check_rate_limit(request, body)
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": decision.detail},
                headers={"Retry-After": str(decision.retry_after)},
            )

        return await call_next(request)
