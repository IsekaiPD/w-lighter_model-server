from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .infra.locales import KO_JA, LOCALE_REGISTRY, LocaleResources
from .infra.project_paths import package_project_root


class TranslationMode(str, Enum):
    # 레거시/v2 파이프라인 폐지 후 단일 모드만 유지.
    V3_LITERARY_PACKAGE = "v3_literary_package"


ALLOWED_TRANSLATION_MODELS = (
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-5.5",
    "gpt-5-mini",
    "gpt-4.1-mini",
)

# 텍스트(채팅) 모델 단일 노브 — guide/character/relationship과 같은 env(WLIGHTER_TEXT_MODEL) 공유.
# 과거 품질모드별(fast/standard/quality/baseline) 모델 차등은 폐지하고 한 모델로 통일.
DEFAULT_TEXT_MODEL = os.getenv("WLIGHTER_TEXT_MODEL", "gpt-5.4-mini")

# Qdrant 접속: QDRANT_URL이 있으면 서버 모드(url=, self-host 컨테이너), 비면 임베디드(path=) 폴백.
# core/config.py settings.qdrant_url(/health·lifespan용)과 같은 env를 공유한다.
DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "").strip() or None

# kculture 문화 각주 검색 임계치(코사인). 서술형 원문 vs 서술형 카드는 KURE 코사인이 0.55~0.6 근처라
# 0.6이면 정답 카드(예: 0.581)도 잘려 endnotes가 안 뜬다. 기본 0.55(정답 통과·과도 주석 억제 균형).
# 올리면 각주 보수적, 내리면 적극적. env로 배포별 조절.
DEFAULT_ANNOTATION_SCORE_THRESHOLD = float(os.getenv("WLIGHTER_ANNOTATION_SCORE_THRESHOLD", "0.55"))


def validate_translation_model(model: str, *, field_name: str = "model") -> str:
    normalized = str(model or "").strip()
    if normalized not in ALLOWED_TRANSLATION_MODELS:
        raise ValueError(
            f"Unsupported {field_name}: {model}. Allowed models: {', '.join(ALLOWED_TRANSLATION_MODELS)}"
        )
    return normalized


@dataclass(slots=True)
class PipelineConfig:
    locale: str = KO_JA.locale
    mode: TranslationMode | str = TranslationMode.V3_LITERARY_PACKAGE
    resources: LocaleResources | None = None
    rag_dataset_path: Path | None = None
    idiom_augmentation_paths: tuple[Path, ...] | list[Path] | None = None
    annotation_dataset_path: Path | None = None
    cultural_terms_path: Path | None = None
    inspection_prompt_path: Path | None = None
    embedding_model: str = "nlpai-lab/KURE-v1"
    translation_model: str | None = None
    review_model: str | None = None
    allowed_models: tuple[str, ...] = ALLOWED_TRANSLATION_MODELS
    model_override: str | None = None
    idiom_top_k: int = 3
    idiom_return_k: int = 15
    score_threshold: float = 0.6
    annotation_top_k: int = 2
    annotation_return_k: int = 10
    annotation_score_threshold: float = DEFAULT_ANNOTATION_SCORE_THRESHOLD
    mock: bool = False
    embedding_cache_dir: Path | None = None
    chunk_strategy: str = "sentence"
    qdrant_path: str = "qdrant_local"
    qdrant_url: str | None = DEFAULT_QDRANT_URL

    def __post_init__(self) -> None:
        self.allowed_models = tuple(str(model).strip() for model in (self.allowed_models or ALLOWED_TRANSLATION_MODELS))
        override = self.model_override
        if override is not None:
            override = validate_translation_model(override, field_name="model override")
            self.model_override = override

        # 모델은 단일 노브(WLIGHTER_TEXT_MODEL, 기본 gpt-5.4-mini)로 통일. translation/review 동일.
        if self.translation_model is None:
            self.translation_model = override or DEFAULT_TEXT_MODEL
        else:
            self.translation_model = validate_translation_model(self.translation_model, field_name="translation_model")

        if self.review_model is None:
            self.review_model = override or DEFAULT_TEXT_MODEL
        else:
            self.review_model = validate_translation_model(self.review_model, field_name="review_model")

    @property
    def model_override_used(self) -> bool:
        return self.model_override is not None

    def build_metadata(
        self,
        *,
        source_side_rag_enabled: bool,
        rag_enabled: bool,
        terminology_enabled: bool,
        glossary_enabled: bool,
        review_enabled: bool,
        inspection_enabled: bool,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "mode": self.resolved_mode().value,
            "translation_model": self.translation_model,
            "review_model": self.review_model,
            "model": self.translation_model,
            "model_override_used": self.model_override_used,
            "allowed_models": list(self.allowed_models),
            "source_side_rag_enabled": source_side_rag_enabled,
            "rag_enabled": rag_enabled,
            "terminology_enabled": terminology_enabled,
            "glossary_enabled": glossary_enabled,
            "review_enabled": review_enabled,
            "inspection_enabled": inspection_enabled,
        }
        if extra:
            metadata.update(extra)
        return metadata

    def resolved_resources(self) -> LocaleResources:
        if self.resources is not None:
            return self.resources
        if self.locale not in LOCALE_REGISTRY:
            raise KeyError(f"Unknown locale: {self.locale}")
        return LOCALE_REGISTRY[self.locale]

    def resolved_mode(self) -> TranslationMode:
        if isinstance(self.mode, TranslationMode):
            return self.mode
        try:
            return TranslationMode(str(self.mode))
        except ValueError as exc:
            raise ValueError(f"Unknown translation mode: {self.mode}") from exc

    def resolved_rag_dataset_path(self) -> Path:
        return Path(self.rag_dataset_path or self.resolved_resources().rag_dataset_path)

    def resolved_idiom_augmentation_paths(self) -> tuple[Path, ...]:
        if self.idiom_augmentation_paths is not None:
            return tuple(Path(path) for path in self.idiom_augmentation_paths)
        if self.resources is None and self.locale not in LOCALE_REGISTRY:
            return ()
        return tuple(Path(path) for path in self.resolved_resources().idiom_augmentation_paths)

    def resolved_annotation_dataset_path(self) -> Path:
        if self.annotation_dataset_path is not None:
            return Path(self.annotation_dataset_path)
        return package_project_root(Path(__file__)) / "data" / "annotation_rag" / "kculture_rag_documents_reviewed.json"

    def resolved_cultural_terms_path(self) -> Path:
        if self.cultural_terms_path is not None:
            return Path(self.cultural_terms_path)
        return package_project_root(Path(__file__)) / "data" / "cultural_terms" / "ko_cultural_terms.json"

    def resolved_inspection_prompt_path(self) -> Path:
        return Path(self.inspection_prompt_path or self.resolved_resources().inspection_prompt_path)

    def resolved_embedding_cache_dir(self) -> Path:
        if self.embedding_cache_dir is not None:
            return Path(self.embedding_cache_dir)
        return package_project_root(Path(__file__)) / "data" / "embedding_cache"

    _IDIOM_COLLECTION_BY_LOCALE = {
        "ko_ja": "idiom_jp",
        "ko_en_us": "idiom_us",
        "ko_zh_cn": "idiom_cn",
        "ko_th_th": "idiom_th",
    }

    def resolved_idiom_collection(self) -> str:
        try:
            return self._IDIOM_COLLECTION_BY_LOCALE[self.locale]
        except KeyError as exc:
            raise KeyError(f"No idiom collection mapped for locale: {self.locale}") from exc

    def resolved_annotation_collection(self) -> str:
        return "kculture"

    def resolved_qdrant_path(self) -> Path:
        path = Path(self.qdrant_path)
        if path.is_absolute():
            return path
        return package_project_root(Path(__file__)) / path
