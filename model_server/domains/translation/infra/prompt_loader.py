from __future__ import annotations

import re
from pathlib import Path

from ..config import PipelineConfig
from .project_paths import cultural_review_prompt_root, repository_root


LOCALE_CONSTRAINT_FILES: dict[str, str] = {
    "ko_ja": "CULTURAL_CONSTRAINTS_JP.md",
    "ko_en_us": "CULTURAL_CONSTRAINTS_US.md",
    "ko_zh_cn": "CULTURAL_CONSTRAINTS_CN.md",
    "ko_th_th": "CULTURAL_CONSTRAINTS_TH.md",
}


def extract_prompt_text(raw_text: str) -> str:
    """Extract prompt content from markdown files that wrap prompts in Python fences."""
    triple_quote_match = re.search(r"\w+\s*=\s*\"\"\"(.*?)\"\"\"", raw_text, re.DOTALL)
    if triple_quote_match:
        return triple_quote_match.group(1).strip()

    fenced_match = re.search(r"```(?:python)?\s*(.*?)```", raw_text, re.DOTALL)
    if fenced_match:
        return extract_prompt_text(fenced_match.group(1))

    return raw_text.strip()


def prompt_root() -> Path:
    return cultural_review_prompt_root(Path(__file__))


def runtime_prompt_root() -> Path:
    return repository_root(Path(__file__)) / "prompts" / "agent_runtime"


def load_prompt_file(path: Path) -> str:
    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    return extract_prompt_text(prompt_path.read_text(encoding="utf-8"))


def load_inspector_prompt(config: PipelineConfig) -> str:
    return load_prompt_file(config.resolved_inspection_prompt_path())


def load_locale_constraints(locale: str) -> str:
    try:
        file_name = LOCALE_CONSTRAINT_FILES[locale]
    except KeyError as exc:
        raise KeyError(f"No cultural constraint prompt registered for locale: {locale}") from exc
    return load_prompt_file(prompt_root() / file_name)


# Per-language register guidance for the voice reviewer: how each target language realizes
# the speech-register distinctions (honorifics / politeness) carried by the Korean source.
LOCALE_REGISTER_GUIDES: dict[str, str] = {
    "ko_ja": (
        "Japanese: apply correct speech registers (敬語 / タメ口) per character. "
        "Match the source's honorific relationships—keep 敬語 where the speaker defers, タメ口 between peers."
    ),
    "ko_zh_cn": (
        "Chinese: Mandarin has weak grammatical honorifics, so register lives in word choice, "
        "address terms (您/你), and tone. Keep natural 网络文学-style prose and preserve the social distance of the source."
    ),
    "ko_th_th": (
        "Thai: apply appropriate politeness levels per character and narrator "
        "(particles like ครับ/ค่ะ, pronoun choices). Match each speaker's deference to the source."
    ),
    "ko_en_us": (
        "English (US): English has no grammatical honorific system, so carry register through diction, "
        "contractions, and formality of phrasing—formal vs. casual—rather than honorific markers."
    ),
}


def load_register_guide(locale: str) -> str:
    """Return the target-language register guidance for the voice reviewer.

    Soft lookup: unknown locale -> empty string (reviewer still runs without it).
    """
    return LOCALE_REGISTER_GUIDES.get(locale, "")


def load_runtime_prompt(file_name: str) -> str:
    return load_prompt_file(runtime_prompt_root() / file_name)
