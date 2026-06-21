# syntax=docker/dockerfile:1
# w-lighter MODEL 서버 (FastAPI) — 멀티스테이지.
# 빌드: docker compose build (컨텍스트=model_server/) / 실행: docker compose up
# 시크릿(.env)은 이미지에 굽지 않는다 — 런타임 env_file 주입(.dockerignore가 .env 제외).

# ===== 1) builder: 의존성 설치 (빌드 도구는 이 스테이지에만) =====
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 일부 패키지(예: kiwipiepy) 휠 미제공 환경 대비 toolchain. 런타임 이미지엔 미포함(멀티스테이지).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# 의존성을 venv에 격리 설치 → 런타임 스테이지로 통째 복사.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
# torch는 CPU 전용 휠로 먼저 설치(기본 인덱스는 CUDA 빌드 → 이미지 수 GB 비대).
# sentence-transformers가 이 torch를 재사용하므로 CUDA 토치를 끌어오지 않는다.
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

# ===== 2) runtime: 슬림 실행 이미지 =====
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/cache/huggingface

# 비루트 유저 + HF 캐시 디렉터리(KURE 모델 캐시 볼륨 마운트 지점).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /cache/huggingface \
    && chown -R appuser:appuser /cache

WORKDIR /app

# 빌더의 venv(의존성) 복사.
COPY --from=builder /opt/venv /opt/venv

# 앱 코드 복사(.dockerignore가 .env·캐시·로컬DB 제외).
COPY --chown=appuser:appuser . .

# WORKDIR /app 자체는 root 소유(COPY --chown은 복사된 파일만 chown) → appuser가 새 파일 생성 불가.
# rdb 기본값에서 DATABASE_URL 없이 뜰 때 SQLite 폴백(/app/wlighter_local.db) 쓰기를 위해 디렉터리도 appuser로.
# (prod는 MySQL DATABASE_URL이라 무관하나, out-of-box 컨테이너가 DB 쓰기에서 깨지지 않도록.)
RUN chown appuser:appuser /app

USER appuser

EXPOSE 8000

# /health 는 외부 의존 없는 가벼운 엔드포인트 → 컨테이너 헬스체크에 사용.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
