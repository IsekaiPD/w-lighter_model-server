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


DEFAULT_QUALITY_MODE = "standard"
ALLOWED_QUALITY_MODES = ("fast", "standard", "quality", "baseline")
ALLOWED_TRANSLATION_MODELS = (
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-5.5",
    "gpt-5-mini",
    "gpt-4.1-mini",
)
MODEL_PROFILES: dict[str, dict[str, str]] = {
    "fast": {
        "translation_model": "gpt-5.4-nano",
        "review_model": "gpt-5.4-nano",
    },
    "standard": {
        "translation_model": "gpt-5.4-mini",
        "review_model": "gpt-5.4-mini",
    },
    "quality": {
        "translation_model": "gpt-5.4-mini",
        "review_model": "gpt-5.4-mini",
    },
    "baseline": {
        "translation_model": "gpt-4.1-mini",
        "review_model": "gpt-4.1-mini",
    },
}
MODEL_PROFILE_ENV_VARS: dict[str, dict[str, str]] = {
    "fast": {
        "translation_model": "WLIGHTER_FAST_TRANSLATION_MODEL",
        "review_model": "WLIGHTER_FAST_REVIEW_MODEL",
    },
    "standard": {
        "translation_model": "WLIGHTER_STANDARD_TRANSLATION_MODEL",
        "review_model": "WLIGHTER_STANDARD_REVIEW_MODEL",
    },
    "quality": {
        "translation_model": "WLIGHTER_QUALITY_TRANSLATION_MODEL",
        "review_model": "WLIGHTER_QUALITY_REVIEW_MODEL",
    },
}


def _resolve_profile_env_model(profile_name: str, field_name: str) -> str | None:
    env_name = MODEL_PROFILE_ENV_VARS.get(profile_name, {}).get(field_name)
    if not env_name:
        return None
    value = os.getenv(env_name, "").strip()
    if not value:
        return None
    return validate_translation_model(value, field_name=env_name)


def normalize_quality_mode(value: str | None) -> str:
    normalized = str(value or DEFAULT_QUALITY_MODE).strip().lower()
    if normalized not in MODEL_PROFILES:
        raise ValueError(
            f"Unsupported qualityMode: {value}. Allowed values: {', '.join(ALLOWED_QUALITY_MODES)}"
        )
    return normalized


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
    quality_mode: str = DEFAULT_QUALITY_MODE
    model_profile_name: str | None = None
    translation_model: str | None = None
    review_model: str | None = None
    allowed_models: tuple[str, ...] = ALLOWED_TRANSLATION_MODELS
    model_override: str | None = None
    idiom_top_k: int = 3
    idiom_return_k: int = 15
    score_threshold: float = 0.6
    annotation_top_k: int = 2
    annotation_return_k: int = 10
    annotation_score_threshold: float = 0.6
    mock: bool = False
    embedding_cache_dir: Path | None = None
    chunk_strategy: str = "sentence"
    qdrant_path: str = "qdrant_local"

    def __post_init__(self) -> None:
        self.allowed_models = tuple(str(model).strip() for model in (self.allowed_models or ALLOWED_TRANSLATION_MODELS))
        self.quality_mode = normalize_quality_mode(self.quality_mode)
        self.model_profile_name = str(self.model_profile_name or self.quality_mode).strip().lower()
        if self.model_profile_name not in MODEL_PROFILES:
            raise ValueError(
                f"Unsupported model profile: {self.model_profile_name}. "
                f"Allowed profiles: {', '.join(sorted(MODEL_PROFILES))}"
            )

        profile = MODEL_PROFILES[self.model_profile_name]
        override = self.model_override
        if override is not None:
            override = validate_translation_model(override, field_name="model override")
            self.model_override = override

        profile_translation_model = _resolve_profile_env_model(self.model_profile_name, "translation_model")
        profile_review_model = _resolve_profile_env_model(self.model_profile_name, "review_model")

        if self.translation_model is None:
            self.translation_model = override or profile_translation_model or profile["translation_model"]
        else:
            self.translation_model = validate_translation_model(self.translation_model, field_name="translation_model")

        if self.review_model is None:
            self.review_model = override or profile_review_model or profile["review_model"]
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
            "quality_mode": self.quality_mode,
            "model_profile": self.model_profile_name,
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
