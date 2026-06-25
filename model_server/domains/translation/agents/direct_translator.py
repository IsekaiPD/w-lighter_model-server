"""직접 번역 엔진 부품 (순수 스텝).

원문을 한 번 번역하고 번역 안전성(잔류 한글/소스 카피/locale 준수)을
점검한 뒤, 필요하면 strict 재시도까지 수행한다. 그래프의 `translate_once`
콜백이 호출한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import PipelineConfig
from .translator import Translator


@dataclass(slots=True)
class DirectTranslationResult:
    mode: str
    final_translation: str
    draft: dict[str, Any]
    metadata: dict[str, Any]


class DirectTranslator:
    """원문 1회 번역 + 번역 안전성 점검 + strict 재시도. 진입점은 translate_once."""

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self.translator = Translator(self.config)

    # ------------------------------------------------------------------ #
    # 공개 진입점
    # ------------------------------------------------------------------ #
    def translate_once(
        self,
        source_text: str,
        *,
        memory_context: str = "",
        strict_locale_retry: bool = False,
        retry_attempt: int = 0,
        debug_capture: dict[str, Any] | None = None,
    ) -> DirectTranslationResult:
        initial_result = self._run_once(
            source_text,
            memory_context=memory_context,
            strict_locale_retry=strict_locale_retry,
            retry_attempt=retry_attempt,
        )
        final_result = self._finalize(source_text, initial_result, memory_context=memory_context)
        if debug_capture and debug_capture.get("enabled"):
            artifact = self._write_debug_artifact(
                final_result,
                attempt_name=str(debug_capture.get("attemptName") or "translation_attempt"),
                artifact_dir=debug_capture.get("artifactDir"),
                prompt_preview=str(debug_capture.get("promptPreview") or memory_context or ""),
            )
            if artifact:
                final_result.metadata = {**final_result.metadata, "debug_artifact": artifact}
        return final_result

    # ------------------------------------------------------------------ #
    # 번역 1회 + 마무리(재시도)
    # ------------------------------------------------------------------ #
    def _run_once(
        self,
        source_text: str,
        *,
        memory_context: str = "",
        strict_locale_retry: bool = False,
        retry_attempt: int = 0,
    ) -> DirectTranslationResult:
        draft = self.translator.translate(
            source_text,
            [],
            memory_context=memory_context,
            translation_profile=None,
            source_analysis=None,
            include_rag_context=False,
            strict_locale_retry=strict_locale_retry,
            retry_attempt=retry_attempt,
        )
        resources = self.config.resolved_resources()
        locale_meta = self._locale_adherence_metadata(
            source_text=source_text,
            final_translation=draft.translation,
            locale=resources.locale,
            target_language_name=resources.target_language,
        )
        return DirectTranslationResult(
            mode="direct_only",
            final_translation=draft.translation,
            draft=asdict(draft),
            metadata=self._metadata(extra=locale_meta),
        )

    def _finalize(
        self,
        source_text: str,
        initial_result: DirectTranslationResult,
        *,
        memory_context: str = "",
    ) -> DirectTranslationResult:
        initial_metadata = initial_result.metadata
        # 첫 번역가 자동 재번역은 기본 off(config.translation_safety_retry_enabled). 방침: 1패스만.
        retry_attempted = bool(self.config.translation_safety_retry_enabled) and self._should_retry_translation_safety(initial_metadata)
        retry_result: DirectTranslationResult | None = None
        final_result = initial_result
        if retry_attempted:
            retry_result = self._run_once(
                source_text,
                memory_context=memory_context,
                strict_locale_retry=True,
                retry_attempt=1,
            )
            final_result = retry_result

        final_metadata = final_result.metadata
        if not retry_attempted:
            retry_success: bool | None = None
        else:
            retry_success = not self._translation_safety_is_hard_fail(final_metadata)

        final_result.metadata = {
            **final_metadata,
            "translation_safety_retry_attempted": retry_attempted,
            "translation_safety_retry_count": 1 if retry_attempted else 0,
            "initial_translation_safety": initial_metadata["translation_safety"],
            "final_translation_safety": final_metadata["translation_safety"],
            "initial_locale_adherence_status": initial_metadata["locale_adherence_status"],
            "final_locale_adherence_status": final_metadata["locale_adherence_status"],
            "initial_source_copy_status": initial_metadata["source_copy_status"],
            "final_source_copy_status": final_metadata["source_copy_status"],
            "initial_source_copy_suspected": initial_metadata["source_copy_suspected"],
            "final_source_copy_suspected": final_metadata["source_copy_suspected"],
            "retry_translation_model": retry_result.metadata["translation_model"] if retry_result else None,
            "retry_prompt_hash": retry_result.draft["prompt_debug"].get("prompt_hash") if retry_result else None,
            "retry_success": retry_success,
        }
        return final_result

    def _metadata(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.config.build_metadata(
            source_side_rag_enabled=False,
            rag_enabled=False,
            terminology_enabled=False,
            glossary_enabled=False,
            review_enabled=False,
            inspection_enabled=False,
            extra=extra,
        )

    # ------------------------------------------------------------------ #
    # 번역 안전성 / locale 점검 헬퍼 (re 만 의존)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _target_script_ratio(*, locale: str, latin_chars: int, han_chars: int, japanese_chars: int, thai_chars: int, total: int) -> float:
        if locale == "ko_en_us":
            return latin_chars / total
        if locale == "ko_zh_cn":
            return han_chars / total
        if locale == "ko_th_th":
            return thai_chars / total
        return japanese_chars / total

    @classmethod
    def _pass_threshold_for_locale(cls, locale: str) -> float:
        if locale in {"ko_en_us", "ko_zh_cn"}:
            return 0.3
        return 0.2

    @staticmethod
    def _hangul_spans(text: str) -> list[dict[str, Any]]:
        return [
            {"text": match.group(0), "start": match.start(), "end": match.end(), "length": len(match.group(0))}
            for match in re.finditer(r"[가-힣]+", text)
        ]

    @staticmethod
    def _residual_hangul_ratio(text: str) -> float:
        total = max(len(text), 1)
        return round(len(re.findall(r"[가-힣]", text)) / total, 4)

    @classmethod
    def _is_source_copy_like(
        cls,
        *,
        source_text: str,
        final_translation: str,
        locale: str,
        target_script_ratio: float,
        korean_chars: int,
        total: int,
        residual_hangul_spans: list[dict[str, Any]],
    ) -> bool:
        prefix_len = min(200, len(source_text), len(final_translation))
        source_prefix_match = prefix_len > 0 and source_text[:prefix_len] == final_translation[:prefix_len]
        if source_prefix_match or source_text.strip() == final_translation.strip():
            return True
        if korean_chars / total >= 0.35 and target_script_ratio <= 0.2:
            return True
        if len(residual_hangul_spans) >= 2 and korean_chars / total >= 0.2 and target_script_ratio <= cls._pass_threshold_for_locale(locale):
            return True
        return False

    @classmethod
    def _translation_safety_checks(
        cls,
        *,
        source_text: str,
        final_translation: str,
        locale: str = "ko_ja",
        target_language_name: str = "Japanese",
    ) -> dict[str, Any]:
        total = max(len(final_translation), 1)
        korean_chars = len(re.findall(r"[가-힣]", final_translation))
        latin_chars = len(re.findall(r"[A-Za-z]", final_translation))
        han_chars = len(re.findall(r"[一-鿿]", final_translation))
        japanese_chars = len(re.findall(r"[぀-ヿㇰ-ㇿ一-鿿]", final_translation))
        thai_chars = len(re.findall(r"[฀-๿]", final_translation))
        target_script_ratio = cls._target_script_ratio(
            locale=locale,
            latin_chars=latin_chars,
            han_chars=han_chars,
            japanese_chars=japanese_chars,
            thai_chars=thai_chars,
            total=total,
        )
        prefix_len = min(200, len(source_text), len(final_translation))
        source_prefix_match = prefix_len > 0 and source_text[:prefix_len] == final_translation[:prefix_len]
        residual_hangul_spans = cls._hangul_spans(final_translation)
        residual_hangul_ratio = cls._residual_hangul_ratio(final_translation)
        pass_threshold = cls._pass_threshold_for_locale(locale)
        source_copy_like = cls._is_source_copy_like(
            source_text=source_text,
            final_translation=final_translation,
            locale=locale,
            target_script_ratio=target_script_ratio,
            korean_chars=korean_chars,
            total=total,
            residual_hangul_spans=residual_hangul_spans,
        )
        weak_source_copy_signal = (
            not source_copy_like
            and (
                source_prefix_match
                or (korean_chars / total >= 0.2 and target_script_ratio <= pass_threshold)
                or (len(residual_hangul_spans) >= 2 and residual_hangul_ratio >= 0.08)
            )
        )
        source_copy_status = "fail" if source_copy_like else "warn" if weak_source_copy_signal else "pass"
        source_copy_suspected = source_copy_status == "fail"

        locale_adherence_status = "fail" if source_copy_status == "fail" or target_script_ratio < 0.1 else "pass"
        if locale_adherence_status == "pass" and target_script_ratio < pass_threshold:
            locale_adherence_status = "warn"

        if not residual_hangul_spans:
            residual_hangul_status = "pass"
        else:
            sentence_like_hangul = len(residual_hangul_spans) >= 2 and any(
                span["length"] <= 4 for span in residual_hangul_spans
            )
            if source_copy_status == "fail" or sentence_like_hangul:
                residual_hangul_status = "fail"
            else:
                residual_hangul_status = "warn"

        proper_noun_issues: list[dict[str, Any]] = []
        if residual_hangul_spans and source_copy_status != "fail":
            for span in residual_hangul_spans:
                proper_noun_issues.append(
                    {
                        "issue_type": "possible_transliteration_issue",
                        "span": span["text"],
                        "start": span["start"],
                        "end": span["end"],
                        "length": span["length"],
                    }
                )
        proper_noun_status = "pass"
        if proper_noun_issues:
            proper_noun_status = "warn" if residual_hangul_status != "fail" else "unchecked"

        overall_status = "pass"
        if source_copy_status == "fail" or locale_adherence_status == "fail" or residual_hangul_status == "fail":
            overall_status = "fail"
        elif (
            locale_adherence_status == "warn"
            or residual_hangul_status == "warn"
            or proper_noun_status in {"warn", "unchecked"}
            or source_copy_status == "warn"
        ):
            overall_status = "warn"

        locale_adherence = {
            "status": locale_adherence_status,
            "locale": locale,
            "target_language_name": target_language_name,
            "target_script_ratio": round(target_script_ratio, 4),
            "target_script_threshold": round(pass_threshold, 4),
            "korean_char_ratio": round(korean_chars / total, 4),
            "latin_char_ratio": round(latin_chars / total, 4),
            "han_char_ratio": round(han_chars / total, 4),
            "japanese_char_ratio": round(japanese_chars / total, 4),
            "thai_char_ratio": round(thai_chars / total, 4),
        }
        source_copy = {
            "status": source_copy_status,
            "suspected": source_copy_suspected,
            "source_prefix_match_200": source_prefix_match,
            "source_exact_match": source_text.strip() == final_translation.strip(),
            "source_copy_like": source_copy_like,
            "weak_source_copy_signal": weak_source_copy_signal,
            "reason": (
                "literal source copy or severe source-language leakage"
                if source_copy_status == "fail"
                else "weak source-copy signal"
                if source_copy_status == "warn"
                else "no strong source-copy signal"
            ),
        }
        residual_hangul = {
            "status": residual_hangul_status,
            "ratio": residual_hangul_ratio,
            "spans": residual_hangul_spans,
            "examples": [span["text"] for span in residual_hangul_spans[:5]],
            "reason": (
                "residual Hangul span(s) remain"
                if residual_hangul_spans
                else "no residual Hangul detected"
            ),
        }
        proper_noun_transliteration = {
            "status": proper_noun_status if not proper_noun_issues else proper_noun_status,
            "issues": proper_noun_issues,
        }

        return {
            "locale": locale,
            "target_language_name": target_language_name,
            "raw_model_response_length": len(final_translation),
            "final_translation_length": len(final_translation),
            "source_prefix_match_200": source_prefix_match,
            "korean_char_ratio": round(korean_chars / total, 4),
            "latin_char_ratio": round(latin_chars / total, 4),
            "han_char_ratio": round(han_chars / total, 4),
            "japanese_char_ratio": round(japanese_chars / total, 4),
            "thai_char_ratio": round(thai_chars / total, 4),
            "target_script_ratio": round(target_script_ratio, 4),
            "source_copy_suspected": source_copy_suspected,
            "source_copy_status": source_copy_status,
            "residual_hangul_ratio": residual_hangul_ratio,
            "residual_hangul_status": residual_hangul_status,
            "residual_hangul_spans": residual_hangul_spans,
            "residual_hangul_examples": residual_hangul["examples"],
            "proper_noun_transliteration_status": proper_noun_status,
            "proper_noun_transliteration_issues": proper_noun_issues,
            "locale_adherence_status": locale_adherence_status,
            "overall_translation_safety_status": overall_status,
            "translation_safety": {
                "overall_status": overall_status,
                "locale_adherence": locale_adherence,
                "source_copy": source_copy,
                "residual_hangul": residual_hangul,
                "proper_noun_transliteration": proper_noun_transliteration,
            },
        }

    @classmethod
    def _locale_adherence_metadata(
        cls,
        *,
        source_text: str,
        final_translation: str,
        locale: str = "ko_ja",
        target_language_name: str = "Japanese",
    ) -> dict[str, Any]:
        checks = cls._translation_safety_checks(
            source_text=source_text,
            final_translation=final_translation,
            locale=locale,
            target_language_name=target_language_name,
        )
        return {
            **checks,
            "locale_adherence_status": checks["translation_safety"]["locale_adherence"]["status"],
            "source_copy_suspected": checks["translation_safety"]["source_copy"]["suspected"],
            "source_copy_status": checks["translation_safety"]["source_copy"]["status"],
            "residual_hangul_status": checks["translation_safety"]["residual_hangul"]["status"],
            "residual_hangul_ratio": checks["translation_safety"]["residual_hangul"]["ratio"],
            "residual_hangul_spans": checks["translation_safety"]["residual_hangul"]["spans"],
            "residual_hangul_examples": checks["translation_safety"]["residual_hangul"]["examples"],
            "proper_noun_transliteration_status": checks["translation_safety"]["proper_noun_transliteration"]["status"],
            "proper_noun_transliteration_issues": checks["translation_safety"]["proper_noun_transliteration"]["issues"],
            "overall_translation_safety_status": checks["translation_safety"]["overall_status"],
        }

    @staticmethod
    def _should_retry_translation_safety(metadata: dict[str, Any]) -> bool:
        return (
            metadata.get("source_copy_status") == "fail"
            or metadata.get("locale_adherence_status") == "fail"
            or bool(metadata.get("source_copy_suspected"))
        )

    @staticmethod
    def _translation_safety_is_hard_fail(metadata: dict[str, Any]) -> bool:
        return metadata.get("source_copy_status") == "fail" or metadata.get("locale_adherence_status") == "fail"

    # ------------------------------------------------------------------ #
    # 디버그 아티팩트 (reports/ 하위에만 기록)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _safe_reports_debug_dir(path_value: Any) -> Path | None:
        if not path_value:
            return None
        try:
            target = Path(str(path_value)).resolve()
            reports_root = (Path.cwd() / "reports").resolve()
            target.relative_to(reports_root)
            target.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            return None

    @staticmethod
    def _write_debug_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_debug_artifact(
        self,
        result: DirectTranslationResult,
        *,
        attempt_name: str,
        artifact_dir: Any,
        prompt_preview: str,
    ) -> dict[str, Any] | None:
        target_dir = self._safe_reports_debug_dir(artifact_dir)
        if target_dir is None:
            return None
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", attempt_name).strip("_") or "translation_attempt"
        prefix = target_dir / safe_name
        draft = result.draft or {}
        prompt_debug = dict(draft.get("prompt_debug") or {})
        raw_response = draft.get("raw_response") or {}
        parsed_candidate = str(result.final_translation or "")
        metadata = dict(result.metadata or {})
        spans = list(metadata.get("residual_hangul_spans") or [])
        metrics = {
            "attemptName": attempt_name,
            "promptHash": prompt_debug.get("prompt_hash"),
            "retryPromptHash": prompt_debug.get("retry_prompt_hash"),
            "routeSource": prompt_debug.get("route_source"),
            "strictLocaleRetry": prompt_debug.get("strict_locale_retry"),
            "retryAttempt": prompt_debug.get("retry_attempt"),
            "translationModel": prompt_debug.get("translation_model") or metadata.get("translation_model"),
            "raw_model_response_length": metadata.get("raw_model_response_length") or len(json.dumps(raw_response, ensure_ascii=False)),
            "final_translation_length": len(parsed_candidate),
            "source_prefix_match_200": metadata.get("source_prefix_match_200"),
            "source_copy_suspected": metadata.get("source_copy_suspected"),
            "source_copy_status": metadata.get("source_copy_status"),
            "target_script_ratio": metadata.get("target_script_ratio"),
            "residual_hangul_ratio": metadata.get("residual_hangul_ratio"),
            "residual_hangul_char_count": sum(len(str(span.get("text") or "")) for span in spans if isinstance(span, dict)),
            "hangul_span_count": len(spans),
            "fallbackApplied": bool(metadata.get("fallback_applied") or metadata.get("fallbackApplied")),
            "fallbackReason": metadata.get("fallback_reason") or metadata.get("fallbackReason") or "",
            "candidateDiscarded": bool(metadata.get("candidate_discarded") or metadata.get("candidateDiscarded")),
            "discardReason": metadata.get("discard_reason") or metadata.get("discardReason") or "",
        }
        prompt_metadata = {
            key: value
            for key, value in prompt_debug.items()
            if key not in {"api_key", "authorization", "password", "secret"}
        }
        prompt_metadata["promptPreviewLength"] = len(prompt_preview)
        self._write_debug_text(prefix.with_name(f"{safe_name}_prompt_preview.txt"), prompt_preview[:4000])
        self._write_debug_text(prefix.with_name(f"{safe_name}_prompt_metadata.json"), json.dumps(prompt_metadata, ensure_ascii=False, indent=2) + "\n")
        self._write_debug_text(prefix.with_name(f"{safe_name}_raw_output.txt"), json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n")
        self._write_debug_text(prefix.with_name(f"{safe_name}_parsed_candidate.txt"), parsed_candidate + "\n")
        self._write_debug_text(prefix.with_name(f"{safe_name}_metrics.json"), json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
        return {
            "debugArtifactDir": str(target_dir),
            "rawOutputPath": str(prefix.with_name(f"{safe_name}_raw_output.txt")),
            "parsedCandidatePath": str(prefix.with_name(f"{safe_name}_parsed_candidate.txt")),
            "metricsPath": str(prefix.with_name(f"{safe_name}_metrics.json")),
            "promptPreviewPath": str(prefix.with_name(f"{safe_name}_prompt_preview.txt")),
            "promptMetadataPath": str(prefix.with_name(f"{safe_name}_prompt_metadata.json")),
            "fallbackApplied": metrics["fallbackApplied"],
            "fallbackReason": metrics["fallbackReason"],
            "candidateDiscarded": metrics["candidateDiscarded"],
            "discardReason": metrics["discardReason"],
        }
