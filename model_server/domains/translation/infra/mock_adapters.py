from __future__ import annotations

from typing import Any


def translation_payload(config: Any, resources: Any, source_text: str, retrievals: list[Any]) -> dict[str, Any]:
    reference_ids = [row.item.get("id", "") for row in retrievals if row.item.get("id")]
    decisions = [
        {
            "source_span": ", ".join(row.item.get("ko_anchor_expression", []) or row.item.get("ko_expression", []) or []),
            "reference_id": row.item.get("id", ""),
            "reference_expression": row.item.get("expression", ""),
            "translated_span": row.item.get("expression", ""),
            "decision_type": row.item.get("translation_strategy", "reference"),
            "reason": "Mock mode records the matched RAG row as a deterministic translation decision.",
        }
        for row in retrievals
        if row.item.get("id")
    ]
    return {
        "translation": f"[MOCK {resources.target_language}] {source_text}",
        "strategy": "mock-reference" if retrievals else "mock-direct",
        "rationale": "Mock mode bypassed the external model call and returned a deterministic draft.",
        "reference_ids": reference_ids,
        "translation_decisions": decisions,
        "raw_response": {},
    }


def inspection_payload(resources: Any, source_text: str, translation_under_inspection: str) -> dict[str, Any]:
    # Inspector 새 구조: {summary, issues[]}. mock 은 이슈 없음(빈 배열)으로 결정적 반환.
    return {
        "summary": "[MOCK 검수] 구체적인 문화권 리스크나 현지화 문제는 확인되지 않았습니다.",
        "issues": [],
        "raw_response": {},
    }


def chatbot_payload(user_message: str, source_text: str, reviewed_translation: str) -> dict[str, Any]:
    message = user_message.strip()
    unrelated_markers = ["저녁 메뉴", "메뉴 추천", "???硫붾돱", "吏?媛怨???", "?좎뵪", "?띾떞"]
    if any(marker in message for marker in unrelated_markers):
        return {
            "answer": "번역 검수 및 현지화 지원 범위를 벗어난 요청이라 수정하지 않았습니다. 번역 결과에 대한 질문이나 수정 요청을 입력해 주세요.",
            "proposed_translation": reviewed_translation,
            "change_summary": "No translation change; unrelated request.",
            "needs_user_confirmation": False,
            "raw_response": {},
        }
    vague_markers = ["뭔가 이상", "어색", "별로", "萸붽? ?댁긽", "?댁깋", "蹂꾨줈"]
    if any(marker in message for marker in vague_markers):
        return {
            "answer": "어떤 부분이 어색한지 문장이나 표현을 지정해 주면 더 정확히 제안할 수 있습니다.",
            "proposed_translation": reviewed_translation,
            "change_summary": "Asked for clarification because the requested edit scope was vague.",
            "needs_user_confirmation": False,
            "raw_response": {},
        }
    if "?쒓컯 ?곗씠??" in message and "?쒓컯" not in source_text:
        return {
            "answer": "현재 작업 중인 원문에서 해당 장면을 찾을 수 없습니다.",
            "proposed_translation": reviewed_translation,
            "change_summary": "No change; requested scene was absent from source text.",
            "needs_user_confirmation": False,
            "raw_response": {},
        }
    if any(marker in message for marker in ["사랑", "직역", "표현", "문장", "?щ옉??", "?쎼걮?╉굥", "2踰", "臾몄옣", "?쒗쁽"]):
        proposed = reviewed_translation.replace("愛してる", "好きです").replace("?쎼걮?╉굥", "也썬걤?㎯걲")
        if proposed == reviewed_translation:
            proposed = reviewed_translation + " 好きです"
        return {
            "answer": "이 부분은 직역보다 好きです 쪽이 일본어 독자에게 더 자연스럽습니다. 也썬걤?㎯걲",
            "proposed_translation": proposed,
            "change_summary": "Suggested a more natural Japanese expression.",
            "needs_user_confirmation": True,
            "raw_response": {},
        }
    return {
        "answer": "Mock chatbot: 현재 번역 근거와 검토 결과를 바탕으로 설명하거나 수정안을 제안할 수 있습니다.",
        "proposed_translation": reviewed_translation,
        "change_summary": "No change in mock mode.",
        "needs_user_confirmation": False,
        "raw_response": {},
    }


def image_payload(prompt: str, model: str) -> dict[str, Any]:
    return {
        "type": "mock_image",
        "data": "mock://w-lighter/generated-image",
        "model": model,
        "notice": "AI 생성 이미지입니다.",
        "prompt": prompt,
    }
