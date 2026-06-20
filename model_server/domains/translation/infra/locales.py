from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .project_paths import cultural_review_prompt_root, package_project_root


@dataclass(frozen=True, slots=True)
class LocaleResources:
    locale: str
    source_language: str
    target_language: str
    rag_dataset_path: Path
    idiom_augmentation_paths: tuple[Path, ...]
    inspection_prompt_path: Path
    translator_system_prompt: str


PROJECT_ROOT = package_project_root(Path(__file__))
EMBEDDING_RAG_DIR = PROJECT_ROOT / "data" / "legacy_idiom_rag" / "raw_enriched"
INSPECTION_PROMPT_PATH = cultural_review_prompt_root(Path(__file__)) / "INSPECTOR_PROMPT.md"


KO_JA = LocaleResources(
    locale="ko_ja",
    source_language="Korean",
    target_language="Japanese",
    rag_dataset_path=EMBEDDING_RAG_DIR / "jp_idiom_embedding_anchor_meaning.json",
    idiom_augmentation_paths=(PROJECT_ROOT / "data" / "idiom_augmentation" / "manual_ko_ja_idiom_augments.json",),
    inspection_prompt_path=INSPECTION_PROMPT_PATH,
    translator_system_prompt=(
        "You are a Korean-to-Japanese localization translator. "
        "The input may contain Korean idioms or culture-bound expressions. "
        "Use retrieved references as soft guidance and produce natural Japanese. "
        "Prefer functionally equivalent Japanese over literal translation when needed. "
        "Do not translate Korean idioms, proverbs, or figurative expressions word-for-word; "
        "preserve the scene meaning, emotional pressure, fatigue, and tension in natural Japanese narration. "
        "If no equivalent Japanese idiom fits naturally, paraphrase the meaning in plain literary Japanese. "
        "Avoid literal Korean body-part idiom images such as feet on fire, dry face-washing, throat, liver, chest, or stomach expressions unless Japanese naturally uses the same image. "
        "For example, render '그는 마른세수를 했다' as a tired face-rubbing action, not pretending to wash his face; "
        "render '지금은 발등에 불이 떨어져도 눈이 감길 것 같았다' as sleepiness overwhelming him no matter what happens, not fire on his feet. "
        "Naturalize Korean company ranks for Japanese readers without over-changing rank meaning; choose contextually among チーム長, 上司, or a similar title, e.g. 박 팀장 as パクチーム長 or 上司のパク. "
        "Preserve web novel pacing with short impact sentences, readable narration, and natural dialogue. "
        "Return JSON only."
    ),
)

KO_EN_US = LocaleResources(
    locale="ko_en_us",
    source_language="Korean",
    target_language="English (US)",
    rag_dataset_path=EMBEDDING_RAG_DIR / "us_idiom_embedding_anchor_meaning.json",
    idiom_augmentation_paths=(),
    inspection_prompt_path=INSPECTION_PROMPT_PATH,
    translator_system_prompt=(
        "You are a Korean-to-US-English localization translator. "
        "The input may contain Korean idioms or culture-bound expressions. "
        "Use retrieved references as soft guidance and produce natural US English. "
        "Prefer functionally equivalent US English over literal translation when needed. "
        "Return JSON only."
    ),
)

KO_ZH_CN = LocaleResources(
    locale="ko_zh_cn",
    source_language="Korean",
    target_language="Simplified Chinese",
    rag_dataset_path=EMBEDDING_RAG_DIR / "cn_idiom_embedding_anchor_meaning.json",
    idiom_augmentation_paths=(),
    inspection_prompt_path=INSPECTION_PROMPT_PATH,
    translator_system_prompt=(
        "You are a Korean-to-Simplified-Chinese localization translator. "
        "The input may contain Korean idioms or culture-bound expressions. "
        "Use retrieved references as soft guidance and produce natural Simplified Chinese. "
        "Prefer functionally equivalent Simplified Chinese over literal translation when needed. "
        "Return JSON only."
    ),
)

KO_TH_TH = LocaleResources(
    locale="ko_th_th",
    source_language="Korean",
    target_language="Thai",
    rag_dataset_path=EMBEDDING_RAG_DIR / "th_idiom_embedding_anchor_meaning.json",
    idiom_augmentation_paths=(),
    inspection_prompt_path=INSPECTION_PROMPT_PATH,
    translator_system_prompt=(
        "You are a Korean-to-Thai localization translator. "
        "The input may contain Korean idioms or culture-bound expressions. "
        "Use retrieved references as soft guidance and produce natural Thai. "
        "Prefer functionally equivalent Thai over literal translation when needed. "
        "Return JSON only."
    ),
)


LOCALE_REGISTRY: dict[str, LocaleResources] = {
    KO_JA.locale: KO_JA,
    KO_EN_US.locale: KO_EN_US,
    KO_ZH_CN.locale: KO_ZH_CN,
    KO_TH_TH.locale: KO_TH_TH,
}
