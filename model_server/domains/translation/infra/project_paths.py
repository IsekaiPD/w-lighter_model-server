from __future__ import annotations

from pathlib import Path


def find_ancestor_containing(start: Path, relative_path: str) -> Path:
    """Return the nearest ancestor containing ``relative_path``."""
    resolved_start = Path(start).resolve()
    search_roots = [resolved_start, *resolved_start.parents]
    for root in search_roots:
        if (root / relative_path).exists():
            return root
    raise FileNotFoundError(
        f"Could not find ancestor containing {relative_path!r} from {resolved_start}"
    )


def package_project_root(start: Path | None = None) -> Path:
    """Directory that owns the translation package + its local data (data/, qdrant_local/).

    project_paths.py lives at ``<package>/infra/project_paths.py``이므로 패키지 루트는
    ``parents[1]``. 파일 위치 기준이라 패키지를 통째로 옮겨도 안 깨진다.
    (start 인자는 하위호환용으로만 받고 무시)
    """
    del start
    return Path(__file__).resolve().parents[1]


def repository_root(start: Path | None = None) -> Path:
    """Root that owns the prompts/ folder. 프롬프트가 패키지 내부에 있어 패키지 루트와 같다."""
    del start
    return Path(__file__).resolve().parents[1]


def cultural_review_prompt_root(start: Path | None = None) -> Path:
    return repository_root(start) / "prompts" / "cultural_review"


def review_prompt_root(start: Path | None = None) -> Path:
    """리뷰어 관점 프롬프트(voice/naturalness/cultural/glossary) .md 가 사는 폴더."""
    return repository_root(start) / "prompts" / "review"
