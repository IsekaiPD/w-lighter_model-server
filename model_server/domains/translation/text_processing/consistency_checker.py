from __future__ import annotations

from typing import Any

from .terminology import (
    TERMINOLOGY_POLICY_CONTEXTUAL,
    TERMINOLOGY_POLICY_LOCKED,
    TERMINOLOGY_POLICY_PREFERRED,
    TERMINOLOGY_POLICY_REVIEW,
    TerminologyIssue,
    issue_to_dict,
    present_any,
    terminology_rows_for_locale,
)


def _source_spans(text: str, needle: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = text.find(needle)
    while start != -1:
        spans.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return spans


def _covered_by_longer_row(source_text: str, source: str, longer_sources: list[str]) -> bool:
    source_spans = _source_spans(source_text, source)
    if not source_spans:
        return False
    cover_spans: list[tuple[int, int]] = []
    for longer in longer_sources:
        if source != longer and source in longer:
            cover_spans.extend(_source_spans(source_text, longer))
    if not cover_spans:
        return False
    return all(any(cover_start <= start and end <= cover_end for cover_start, cover_end in cover_spans) for start, end in source_spans)


def check_translation_consistency(
    *,
    source_text: str,
    translated_text: str,
    locale: str,
    memory: dict[str, Any] | list[dict[str, Any]] | None = None,
    terminology: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check noun/proper-noun terminology consistency only.

    This intentionally ignores verbs, adjectives, idiomatic phrasing, and normal
    sentence variation. It evaluates only explicit terminology/glossary rows:
    - locked: exact target required when the source noun/proper noun appears
    - preferred: target or allowed variants pass
    - contextual: reference-only, skipped from enforcement
    """
    terms = terminology if terminology is not None else memory
    issues: list[TerminologyIssue] = []
    checked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    rows = terminology_rows_for_locale(terms, locale)
    longer_sources = [row["source"] for row in rows if row.get("policy") != TERMINOLOGY_POLICY_CONTEXTUAL]

    for row in rows:
        source = row["source"]
        if source not in source_text:
            continue
        policy = row.get("policy") or TERMINOLOGY_POLICY_LOCKED
        expected = row.get("target") or row.get("recommendedTranslation") or ""
        allowed = list(row.get("allowedTranslations") or [])
        if expected and expected not in allowed:
            allowed.insert(0, expected)

        if policy in {TERMINOLOGY_POLICY_CONTEXTUAL, TERMINOLOGY_POLICY_REVIEW}:
            skipped.append(
                {
                    "source": source,
                    "policy": policy,
                    "reason": "contextual/reference-only noun term; not enforced",
                }
            )
            continue
        if _covered_by_longer_row(source_text, source, longer_sources):
            skipped.append(
                {
                    "source": source,
                    "policy": policy,
                    "reason": "covered by a longer noun/proper-noun terminology row",
                }
            )
            continue
        if not expected and not allowed:
            skipped.append(
                {
                    "source": source,
                    "policy": policy,
                    "reason": "no confirmed target translation; candidate only",
                }
            )
            continue

        found = present_any(translated_text, allowed)
        status = "pass" if found else "missing_target"
        if policy == TERMINOLOGY_POLICY_PREFERRED and found and expected and found != expected:
            status = "pass_with_allowed_variant"
        checked.append(
            {
                "source": source,
                "expected": expected,
                "allowed": allowed,
                "found": found,
                "policy": policy,
                "type": row.get("type", "term"),
                "status": status,
            }
        )

        if not found:
            severity = "HIGH" if policy == TERMINOLOGY_POLICY_LOCKED else "MEDIUM"
            issues.append(
                TerminologyIssue(
                    type="terminology_mismatch" if policy == TERMINOLOGY_POLICY_LOCKED else "preferred_term_missing",
                    source=source,
                    expected=expected or ", ".join(allowed),
                    actual="missing",
                    severity=severity,
                    message=(
                        f"Source noun/proper noun '{source}' appears in the original text, but the translation does not contain "
                        f"the expected terminology form '{expected or ', '.join(allowed)}'."
                    ),
                )
            )

    status = "pass" if not issues else "warning"
    return {
        "status": status,
        "checked": checked,
        "skipped": skipped,
        "issues": [issue_to_dict(issue) for issue in issues],
        "summary": (
            "Terminology consistency passed for checked noun/proper-noun terms."
            if not issues
            else f"Terminology consistency found {len(issues)} issue(s)."
        ),
    }
